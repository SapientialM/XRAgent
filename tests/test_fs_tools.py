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
* list_dir
    - 已存在目录 → ok=True，entries 列表里没有 .git/
    - 路径指向文件 → ok=False（因为 is_dir() == False）
    - 路径缺失也走 "不是目录" 同一条 false 分支
    - 路径越出 repo_root → ok=False 含 "目标越界"
* _resolve_inside / _resolve_writable（白盒）
    - 仓库内路径 → (Path, None)
    - 越界路径 → (None, 错误文案)
    - 黑名单命中（write 系列：.env）→ (None, 错误文案)

不在本测试覆盖：二进制解码错误（实现细节、易变）。
"""
from __future__ import annotations

from pathlib import Path

from xragent.tools.fs_tools import (
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
