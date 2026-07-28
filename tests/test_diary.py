"""diary_write 边界条件 + 正常路径。"""
from __future__ import annotations

import time

from xragent.tools.diary_tools import diary_write


def _today_path(repo_root) -> str:
    return str(repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md")


def test_diary_write_happy_path(repo_root):
    r = diary_write(title="hello", body="world")
    assert r["ok"] is True
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "hello" in content
    assert "world" in content


def test_diary_write_appends_multiple(repo_root):
    diary_write(title="first", body="one")
    diary_write(title="second", body="two")
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    content = p.read_text(encoding="utf-8")
    # 每次写入都会产生一行 `## [HH:MM:SS]`
    assert content.count("## [") == 2
    assert "first" in content and "second" in content
    assert "one" in content and "two" in content


def test_diary_write_rejects_empty_title(repo_root):
    r = diary_write(title="", body="body")
    assert r["ok"] is False
    assert "title" in r["error"]


def test_diary_write_rejects_whitespace_only_title(repo_root):
    r = diary_write(title="   \n\t  ", body="body")
    assert r["ok"] is False
    assert "title" in r["error"]


def test_diary_write_rejects_empty_body(repo_root):
    r = diary_write(title="t", body="")
    assert r["ok"] is False
    assert "body" in r["error"]


def test_diary_write_rejects_whitespace_only_body(repo_root):
    r = diary_write(title="t", body="\n  \n")
    assert r["ok"] is False
    assert "body" in r["error"]


def test_diary_write_rejects_non_string_inputs(repo_root):
    # 防止调用方传 int / None 等类型时悄悄写出 "## [...] None" 这种脏条目。
    r = diary_write(title=None, body="body")  # type: ignore[arg-type]
    assert r["ok"] is False
    r2 = diary_write(title="t", body=123)  # type: ignore[arg-type]
    assert r2["ok"] is False


def test_diary_write_creates_file_on_first_call(repo_root):
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    assert not p.exists()
    r = diary_write(title="init", body="first entry")
    assert r["ok"] is True
    assert p.exists()
    assert p.read_text(encoding="utf-8").startswith("\n## ")


# ---------------------------------------------------------------------------
# 边界条件（先前未覆盖）：
#   * 校验失败 → 不应触碰目标文件（不能污染日记）
#   * 返回的 path 必须是相对 repo_root 的 POSIX 形式
#   * body 末尾多个换行被 rstrip 吃掉，块之间不出现多余空行
#   * Unicode / emoji 标题与正文原样写入
#   * 非字符串错误信息要明确指出字段名 + 实际类型
# ---------------------------------------------------------------------------


def test_diary_write_validation_failure_does_not_touch_file(repo_root):
    """校验失败时绝对不能 append 任何东西：日记文件应当不存在。

    这条测试锁定 diary_write 的"先校验、再写盘"语义，避免实现回退成
    "先 open() 再报错"这种会让目标文件凭空出现的危险形态。
    """
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    assert not p.exists()

    # 三种失败路径都不应产生文件
    for bad_title, bad_body in [
        ("", "body"),  # 空 title
        ("t", ""),  # 空 body
        (None, "body"),  # 非字符串 title
        ("t", ["a", "b"]),  # 非字符串 body
    ]:
        r = diary_write(title=bad_title, body=bad_body)  # type: ignore[arg-type]
        assert r["ok"] is False, f"应当被拒，但通过了: {(bad_title, bad_body)!r}"

    assert not p.exists(), "校验失败时 diary 文件不应被创建"


def test_diary_write_validation_failure_does_not_append_to_existing_file(repo_root):
    """已有文件的情况下，校验失败也不应 append / truncate。

    先写一条合法条目让文件存在并有内容；再连续尝试各种非法参数；
    文件大小应当保持不变。
    """
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    diary_write(title="seed", body="seed-body")
    before = p.read_bytes()
    assert b"seed" in before

    for bad_title, bad_body in [
        ("", "body"),
        ("   ", "body"),
        ("t", "\n\n"),
        (None, "body"),  # type: ignore[arg-type]
        ("t", {"k": "v"}),  # type: ignore[arg-type]
    ]:
        r = diary_write(title=bad_title, body=bad_body)  # type: ignore[arg-type]
        assert r["ok"] is False

    after = p.read_bytes()
    assert before == after, "校验失败时既有 diary 文件不应被改动"


def test_diary_write_returns_relative_posix_path(repo_root):
    """返回值里的 path 应是相对 repo_root 的 POSIX 形式（用 `/` 分隔）。"""
    r = diary_write(title="path-check", body="body")
    assert r["ok"] is True
    assert "path" in r
    # 必须以 diary/ 开头、相对路径、且使用 POSIX 分隔符
    assert r["path"].startswith("diary/")
    assert "\\" not in r["path"]
    assert r["path"].endswith(".md")


def test_diary_write_strips_trailing_newlines_in_body(repo_root):
    """body 末尾的多个换行应被 rstrip 吃掉，避免块之间出现多余空行。

    实现里用的是 f"\\n## [{ts}] {title}\\n\\n{body.rstrip()}\\n"，
    rstrip 把 body 末尾的 \\n\\n\\n 全部清掉 → 下一个块的开头仍是单个 \\n## 。
    """
    diary_write(title="a", body="line1\nline2\n\n\n\n\n")
    diary_write(title="b", body="line3\n")
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    content = p.read_text(encoding="utf-8")

    # 两次写入应当形成 2 个 `## [` 块
    assert content.count("## [") == 2
    # rstrip 不应让两个块的标题行之间出现连续 3 个以上换行（即空段落）
    # 块结构：\n## [ts] a\n\nline1\nline2\n## [ts] b\n\nline3\n
    import re
    gap_pattern = re.compile(r"\n{3,}")  # 3+ 连续换行 = 多余空段
    assert not gap_pattern.search(content), f"块之间出现多余空行: {content!r}"
    assert "line1\nline2" in content
    assert "line3" in content


def test_diary_write_handles_unicode_title_and_body(repo_root):
    """中文 / emoji 标题与正文应被原样写入（utf-8，markdown 元字符不解释）。"""
    r = diary_write(
        title="🧪 调试：测试边界",
        body="第一行：中文 + emoji 🌱\n第二行：带 `code` 和 **markdown**\n",
    )
    assert r["ok"] is True
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    content = p.read_text(encoding="utf-8")
    assert "🧪 调试：测试边界" in content
    assert "🌱" in content
    # markdown 字符按字面写入，不展开
    assert "`code`" in content
    assert "**markdown**" in content


def test_diary_write_non_string_title_error_mentions_field_and_type(repo_root):
    """非字符串 title 的错误信息必须同时包含字段名和实际类型名。"""
    r = diary_write(title=None, body="body")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "title" in r["error"]
    assert "NoneType" in r["error"]

    r2 = diary_write(title=42, body="body")  # type: ignore[arg-type]
    assert r2["ok"] is False
    assert "title" in r2["error"]
    assert "int" in r2["error"]


def test_diary_write_non_string_body_error_mentions_field_and_type(repo_root):
    """非字符串 body 的错误信息必须同时包含字段名和实际类型名。"""
    r = diary_write(title="t", body=["x", "y"])  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "body" in r["error"]
    assert "list" in r["error"]

    r2 = diary_write(title="t", body={"k": "v"})  # type: ignore[arg-type]
    assert r2["ok"] is False
    assert "body" in r2["error"]
    assert "dict" in r2["error"]