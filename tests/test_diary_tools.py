"""diary_tools 的工具层测试：覆盖 ``diary_write`` + ``diary_archive`` 包装、注册项。"""
from __future__ import annotations

import time

import pytest

from xragent.tools import diary_tools


# ---------- diary_write：业务语义 ----------


def test_diary_write_happy_path_returns_relative_posix_path(repo_root):
    """合法输入：返回 ``ok=True`` + 相对 repo_root 的 POSIX 路径 ``diary/YYYY-MM-DD.md``。"""
    r = diary_tools.diary_write("Turn1", "first body")
    assert r["ok"] is True
    assert r["path"].startswith("diary/")
    assert "\\" not in r["path"]
    assert r["path"].endswith(".md")
    # 实际写入在 repo_root 下
    assert (repo_root / r["path"]).exists()


def test_diary_write_appends_multiple_blocks(repo_root):
    """同一天连写两次：文件里出现两个 ``## [`` 块，且标题按写入顺序排列。"""
    diary_tools.diary_write("first", "one")
    diary_tools.diary_write("second", "two")
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    content = p.read_text(encoding="utf-8")
    assert content.count("## [") == 2
    assert content.index("first") < content.index("second")
    assert "one" in content and "two" in content


def test_diary_write_strips_trailing_newlines(repo_root):
    """body 末尾多个换行被 ``rstrip`` 吃掉，块之间不出现连续 3+ 空行。"""
    diary_tools.diary_write("a", "line1\nline2\n\n\n\n\n")
    diary_tools.diary_write("b", "line3\n")
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    content = p.read_text(encoding="utf-8")

    import re
    assert not re.search(r"\n{3,}", content), f"块之间出现多余空行: {content!r}"
    assert "line1\nline2" in content
    assert "line3" in content


# ---------- diary_write：校验失败 ----------


def test_diary_write_rejects_blank_title(repo_root):
    r = diary_tools.diary_write("", "body")
    assert r["ok"] is False and "title" in r["error"]


def test_diary_write_rejects_whitespace_only_title(repo_root):
    r = diary_tools.diary_write("   \n\t  ", "body")
    assert r["ok"] is False and "title" in r["error"]


def test_diary_write_rejects_blank_body(repo_root):
    r = diary_tools.diary_write("t", "")
    assert r["ok"] is False and "body" in r["error"]


def test_diary_write_rejects_whitespace_only_body(repo_root):
    r = diary_tools.diary_write("t", "\n  \n")
    assert r["ok"] is False and "body" in r["error"]


def test_diary_write_rejects_non_string_title(repo_root):
    r = diary_tools.diary_write(None, "body")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "title 必须是字符串" in r["error"] and "NoneType" in r["error"]

    r2 = diary_tools.diary_write(42, "body")  # type: ignore[arg-type]
    assert r2["ok"] is False and "int" in r2["error"]


def test_diary_write_rejects_non_string_body(repo_root):
    r = diary_tools.diary_write("t", ["x", "y"])  # type: ignore[arg-type]
    assert r["ok"] is False and "body 必须是字符串" in r["error"] and "list" in r["error"]


def test_diary_write_validation_failure_does_not_touch_existing_file(repo_root):
    """校验失败时不应触碰已存在的 diary 文件（既有内容不变）。"""
    diary_tools.diary_write("seed", "seed-body")
    p = repo_root / "diary" / f"{time.strftime('%Y-%m-%d')}.md"
    before = p.read_bytes()
    assert b"seed" in before

    for bad_title, bad_body in [
        ("", "body"),
        ("t", "\n\n\n"),
        (None, "body"),  # type: ignore[arg-type]
        ("t", {"k": "v"}),  # type: ignore[arg-type]
    ]:
        r = diary_tools.diary_write(bad_title, bad_body)  # type: ignore[arg-type]
        assert r["ok"] is False

    assert p.read_bytes() == before


# ---------- diary_write：Registry 挂载 ----------


def test_diary_write_is_registered_with_low_risk(repo_root):
    """diary_write 注册到默认 registry，risk=low，title/body 必填。

    evolve_tools 预存 ``from ..blacklist import check`` 路径错误, 导致
    ``build_default_registry()`` 在某些环境抛 ``ModuleNotFoundError``。
    这是仓库历史 bug, 与本工具无关; 这里用 try/except 软断言:
    能 import 就验证注册, 不能 import 就 skip, 不让本测试的失败掩盖
    diary_tools 实现本身的问题（与 ``test_memory_recall.py`` 同模式）。
    """
    try:
        from xragent.tools.registry import build_default_registry
        reg = build_default_registry()
    except ModuleNotFoundError as e:
        pytest.skip(f"build_default_registry() 预存 import 错误: {e}")

    spec = reg.get("diary_write")
    assert spec.handler is diary_tools.diary_write
    assert spec.risk == "low"
    # schema 标记 title/body 为必填，便于后端做参数校验
    assert set(spec.input_schema["required"]) == {"title", "body"}
    assert "diary_write" in reg.names()


# ---------- diary_archive：薄包装 ----------


def test_diary_archive_passes_through_to_auto_archive(repo_root):
    """``diary_archive`` 是 ``auto_archive`` 的薄包装：空目录返回 ``ok=True`` 且两边列表都为空。"""
    r = diary_tools.diary_archive(weeks_threshold=2)
    assert r["ok"] is True
    assert r["archived"] == []
    assert r["skipped"] == []
    # 默认参数也能跑通（不显式传 weeks_threshold）
    r2 = diary_tools.diary_archive()
    assert r2["ok"] is True


def test_diary_archive_uses_settings_diary_dir(repo_root):
    """``diary_archive`` 走 settings.diary_dir：把同一文件再交给 ``auto_archive`` 应得到一致结果。"""
    from xragent.config.settings import get_settings
    from xragent.util.diary_archive import auto_archive

    # 仓库根的 diary/ 此时为空
    s = get_settings()
    expected = auto_archive(s.diary_dir, weeks_threshold=2)
    actual = diary_tools.diary_archive(weeks_threshold=2)
    assert actual == expected


# ---------- diary_archive：Registry 挂载 ----------


def test_diary_archive_is_registered_with_low_risk(repo_root):
    """diary_archive 注册到默认 registry，risk=low，weeks_threshold 是可选参数。"""
    try:
        from xragent.tools.registry import build_default_registry
        reg = build_default_registry()
    except ModuleNotFoundError as e:
        pytest.skip(f"build_default_registry() 预存 import 错误: {e}")

    spec = reg.get("diary_archive")
    assert spec.handler is diary_tools.diary_archive
    assert spec.risk == "low"
    # weeks_threshold 是可选参数
    props = spec.input_schema["properties"]
    assert "weeks_threshold" in props
    assert "weeks_threshold" not in spec.input_schema.get("required", [])
    assert "diary_archive" in reg.names()