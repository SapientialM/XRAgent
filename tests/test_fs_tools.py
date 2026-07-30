"""fs_tools.read_file / fs_tools.list_dir：边界条件。

背景：tests/test_registry.py 已断言这两个工具是 low-risk 核心工具，
但没有任何测试真正执行它们的 handler。本文件就是补这个洞。

我们严格按 *当前* 实现写测试（不多不少）：

* read_file
    - 已存在的普通 utf-8 文件 → ok=True，含 content + size + 相对路径
    - 缺失文件 → ok=False
    - 路径指向目录 → ok=False
    - 路径越出 repo_root（绝对路径 & ../ 逃逸）→ ok=False 含 "目标越界"
    - 显式声明：当前 read_file 不查 is_protected（AGENTS.md/.env 等
      读保护还没启用）—— 这一锁定用作未来引入 read 黑名单的快照基线
    - v0.2 新增 max_bytes 参数：
        * 默认 None → 与旧行为完全一致（向后兼容）
        * cap 大于文件 → 全读，truncated=False
        * cap 小于文件 → 截断到首 cap 字节，truncated=True
        * cap=0 / 负数 / 非 int → 退回无上限（对齐 _resolve_timeout 宽松策略）
        * 多字节字符边界被切 → 不 raise，errors="replace" 丢字符保命
* list_dir
    - 已存在目录 → ok=True，entries 列表里没有 .git/
    - 路径指向文件 → ok=False（因为 is_dir() == False）
    - 路径缺失也走 "不是目录" 同一条 false 分支
    - 路径越出 repo_root → ok=False 含 "目标越界"
* _resolve_inside / _resolve_writable（白盒）
    - 仓库内路径 → (Path, None)
    - 越界路径 → (None, 错误文案)
    - 黑名单命中（write 系列：.env）→ (None, 错误文案)
* _read_text_capped（白盒）
    - max_bytes 无效（None/0/负数/str/bool）→ 当无上限，truncated=False
    - 文件 fit → 全文，truncated=False
    - 文件超 cap → 仅前 cap 字节 + truncated=True

不在本测试覆盖：二进制解码错误（实现细节、易变）。
"""
from __future__ import annotations

from pathlib import Path

from xragent.tools.fs_tools import (
    _read_text_capped,
    _resolve_inside,
    _resolve_writable,
    list_dir,
    read_file,
)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


def test_read_file_happy_path_returns_relative_path_and_content(repo_root: Path):
    f = repo_root / "sandbox" / "note.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello\nworld\n", encoding="utf-8")

    out = read_file("sandbox/note.txt")
    assert out["ok"] is True
    assert out["path"] == "sandbox/note.txt"
    assert out["size"] == len("hello\nworld\n")
    assert out["content"] == "hello\nworld\n"
    # v0.2 新增 truncated 字段；默认 max_bytes=None 时必须 False
    assert out["truncated"] is False


def test_read_file_missing_target_returns_ok_false(repo_root: Path):
    """对不存在的文件：返回 ok=False 文案含 '不存在'。"""
    out = read_file("sandbox/does_not_exist.md")
    assert out["ok"] is False
    assert "不存在" in out["error"]


def test_read_file_directory_target_returns_ok_false(repo_root: Path):
    """目标是个目录而非文件 → ok=False。"""
    out = read_file("sandbox")  # conftest 已经 mkdir
    assert out["ok"] is False
    assert "是目录" in out["error"]


def test_read_file_outside_repo_absolute_path_is_blocked(repo_root: Path):
    """绝对路径在 repo_root 之外 → ok=False 含 '目标越界'。"""
    out = read_file("/etc/passwd")
    assert out["ok"] is False
    assert "目标越界" in out["error"]


def test_read_file_escape_via_parent_traversal_is_blocked(repo_root: Path):
    """.. 逃逸到 repo_root 之外同样要被卡住。"""
    out = read_file("../outside_evil.txt")
    assert out["ok"] is False
    assert "目标越界" in out["error"]


def test_read_file_currently_does_not_block_agents_md(repo_root: Path):
    """当前实现只查"越界"，不查 is_protected——锁定这一现状作快照基线。

    一旦后续给 read_file 加上 read 黑名单，本测试应被替换为
    `assert out['ok'] is False`，锁的就是新行为了。
    """
    out = read_file("AGENTS.md")
    assert out["ok"] is True
    assert "TEST DREAM" in out["content"]


# ---- v0.2 max_bytes 参数 --------------------------------------------------------


def test_read_file_max_bytes_default_is_backward_compatible(repo_root: Path):
    """不传 max_bytes / 显式传 None → 与历史行为完全一致（truncated=False）。"""
    f = repo_root / "sandbox" / "long.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("abcdef" * 100, encoding="utf-8")  # 600 bytes

    out_default = read_file("sandbox/long.txt")
    out_explicit = read_file("sandbox/long.txt", max_bytes=None)
    assert out_default == out_explicit
    assert out_default["ok"] is True
    assert out_default["size"] == 600
    assert out_default["truncated"] is False
    assert len(out_default["content"]) == 600


def test_read_file_max_bytes_larger_than_file_is_no_op(repo_root: Path):
    """cap 远大于文件 → 全读、truncated=False。"""
    f = repo_root / "sandbox" / "short.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hi", encoding="utf-8")

    out = read_file("sandbox/short.txt", max_bytes=1000)
    assert out["ok"] is True
    assert out["content"] == "hi"
    assert out["size"] == 2
    assert out["truncated"] is False


def test_read_file_max_bytes_truncates_and_marks_flag(repo_root: Path):
    """cap 小于文件 → 只返前 cap 字节、truncated=True、size=实际返回字符数。"""
    f = repo_root / "sandbox" / "big.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("X" * 10_000, encoding="utf-8")

    out = read_file("sandbox/big.txt", max_bytes=123)
    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["content"]) == 123
    # ASCII 场景下 size (chars) == bytes
    assert out["size"] == 123


def test_read_file_max_bytes_invalid_values_fall_back_to_unlimited(repo_root: Path):
    """0 / 负数 / str / bool → 全部退回"无上限"（对齐 _resolve_timeout 宽松策略）。

    动机: LLM 传错类型时, 我们宁可多吐点字节也别把整次 read 拒了,
    反正 truncated 字段会照实报告。
    """
    f = repo_root / "sandbox" / "doc.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("payload", encoding="utf-8")

    for bad in (0, -1, -100, "", "abc", True, False, 3.14):
        out = read_file("sandbox/doc.txt", max_bytes=bad)  # type: ignore[arg-type]
        assert out["ok"] is True, f"max_bytes={bad!r} should fall back to unlimited"
        assert out["content"] == "payload"
        assert out["truncated"] is False, f"max_bytes={bad!r} must not pretend it truncated"


def test_read_file_max_bytes_at_multi_byte_boundary_does_not_crash(repo_root: Path):
    """cap 切在多字节字符中间 → 不能 UnicodeDecodeError 崩掉工具契约。

    我们用 errors="replace" 解码, 宁可丢字符也保证 dict 返回;
    truncated=True 告诉 LLM 信息确实丢了。
    """
    f = repo_root / "sandbox" / "utf8.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    # "中" 是 3-byte UTF-8; 第 2 字节处截断会切碎它
    f.write_text("中文中文中文", encoding="utf-8")  # 18 bytes
    # 找 1 个不整除 3 的截断点, 让 multi-byte 边界必然被切
    out = read_file("sandbox/utf8.txt", max_bytes=5)
    assert out["ok"] is True, "切在多字节字符中间必须仍 ok=True"
    assert out["truncated"] is True
    # 返回的字符数 <= 5 (可能更少, 因为 decode 已合并 partial bytes)
    assert len(out["content"]) <= 5
    assert isinstance(out["content"], str)


# ---------------------------------------------------------------------------
# _read_text_capped  (白盒: refactor 行为锁)
# ---------------------------------------------------------------------------


def test_read_text_capped_invalid_max_bytes_returns_full(repo_root: Path):
    """max_bytes 无效 → 全文 + truncated=False (与 read_file 公开行为一致)。"""
    f = repo_root / "sandbox" / "x.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello", encoding="utf-8")

    for bad in (None, 0, -1, "abc", True):
        text, truncated = _read_text_capped(f, max_bytes=bad)  # type: ignore[arg-type]
        assert text == "hello"
        assert truncated is False


def test_read_text_capped_within_limit_returns_full(repo_root: Path):
    f = repo_root / "sandbox" / "y.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("12345", encoding="utf-8")

    text, truncated = _read_text_capped(f, max_bytes=10)
    assert text == "12345"
    assert truncated is False

    text, truncated = _read_text_capped(f, max_bytes=5)  # 边界 ==
    assert text == "12345"
    assert truncated is False


def test_read_text_capped_oversize_truncates_to_exact_cap(repo_root: Path):
    f = repo_root / "sandbox" / "z.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("abcdefghij", encoding="utf-8")  # 10 bytes

    text, truncated = _read_text_capped(f, max_bytes=4)
    assert text == "abcd"
    assert truncated is True


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------


def test_list_dir_happy_path_includes_seed_dirs_and_excludes_git(repo_root: Path):
    out = list_dir(".")
    assert out["ok"] is True
    assert out["path"] == "."

    names = [e["name"] for e in out["entries"]]
    # conftest 自动创建了 sandbox/diary/evolve
    assert "sandbox" in names
    assert "diary" in names
    assert "evolve" in names
    # .git 必须被过滤掉
    assert ".git" not in names


def test_list_dir_marks_is_dir_correctly(repo_root: Path):
    (repo_root / "sandbox" / "leaf_file.md").write_text("x", encoding="utf-8")
    out = list_dir("sandbox")
    assert out["ok"] is True
    entries = {e["name"]: e for e in out["entries"]}
    assert entries["sandbox/leaf_file.md"]["is_dir"] is False
    # 文件 size 字段正确
    assert entries["sandbox/leaf_file.md"]["size"] == 1


def test_list_dir_on_a_file_returns_ok_false(repo_root: Path):
    """list_dir 一个文件 → ok=False。缺失路径走同一分支，也覆盖。"""
    f = repo_root / "sandbox" / "lone.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")

    out_file = list_dir("sandbox/lone.txt")
    assert out_file["ok"] is False
    assert "不是目录" in out_file["error"]

    out_missing = list_dir("sandbox/nope/")
    assert out_missing["ok"] is False
    assert "不是目录" in out_missing["error"]


def test_list_dir_outside_repo_is_blocked(repo_root: Path):
    out = list_dir("/")
    assert out["ok"] is False
    assert "目标越界" in out["error"]


# ---------------------------------------------------------------------------
# _resolve_inside / _resolve_writable  (白盒: refactor 行为锁)
# ---------------------------------------------------------------------------


def test_resolve_inside_inside_repo_returns_target_no_error(repo_root: Path):
    """仓库内路径 → (target, None), target.name 准确。"""
    (repo_root / "sandbox" / "note.txt").write_text("x", encoding="utf-8")
    target, err = _resolve_inside("sandbox/note.txt")
    assert err is None
    assert target is not None
    assert target.name == "note.txt"


def test_resolve_inside_outside_repo_returns_none_with_error(repo_root: Path):
    """越界路径 → (None, 错误文案);文案锁 '目标越界'。"""
    target, err = _resolve_inside("/etc/passwd")
    assert target is None
    assert err is not None
    assert "目标越界" in err


def test_resolve_inside_parent_traversal_is_blocked(repo_root: Path):
    """../ 逃逸同路径围栏逻辑, 也走同一条失败分支。"""
    target, err = _resolve_inside("../evil.txt")
    assert target is None
    assert err is not None
    assert "目标越界" in err


def test_resolve_writable_blocks_blacklisted_dotenv(repo_root: Path):
    """_resolve_writable 走 assert_writable: write_blacklist 里的 .env 必须被拒。

    AGENTS.md 当前不在 write_blacklist (settings.write_blacklist), 所以
    这里用 .env 锁"黑名单拦截"。这是 read / write 黑名单分裂的核心契约:
    read_file 路径放行 .env (上面没有这条断言), write_file 必须拦截。
    """
    (repo_root / ".env").write_text("SECRET=1", encoding="utf-8")
    target, err = _resolve_writable(".env")
    assert target is None
    assert err is not None
    assert isinstance(err, str) and err != ""
    assert "受保护" in err


def test_resolve_writable_on_normal_path_returns_target(repo_root: Path):
    """非黑名单的普通路径 → (target, None)。"""
    target, err = _resolve_writable("sandbox/will_be_written.txt")
    assert err is None
    assert target is not None
    assert target.name == "will_be_written.txt"