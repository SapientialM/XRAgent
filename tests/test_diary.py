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
