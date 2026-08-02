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


def test_diary_archive_accepts_zero(repo_root):
    """``weeks_threshold=0`` 合法: 语义为"当周立刻归档", 不应被拒。"""
    r = diary_tools.diary_archive(weeks_threshold=0)
    assert r["ok"] is True
    assert "error" not in r


def test_diary_archive_accepts_max_boundary(repo_root):
    """``weeks_threshold=520`` (10 年 ISO 周) 是上界本身, 应该被允许。"""
    r = diary_tools.diary_archive(weeks_threshold=520)
    assert r["ok"] is True
    assert "error" not in r


# ---------- diary_archive：校验失败 (走 _validate_int_field) ----------


def test_diary_archive_rejects_negative_threshold(repo_root):
    """负数: 错误信息含字段名 + 越界值 + 下界。"""
    r = diary_tools.diary_archive(weeks_threshold=-1)
    assert r["ok"] is False
    assert "weeks_threshold" in r["error"]
    assert "不能小于" in r["error"]
    assert "-1" in r["error"]


def test_diary_archive_rejects_excessive_threshold(repo_root):
    """超过 :data:`_WEEKS_THRESHOLD_MAX` (520 周) 一律拒: 防止 LLM 误传 999999 让语义奇怪请求过线。

    新行为 (round 2026-08-04): 之前没有 max_value clamp, ``weeks_threshold=999999``
    会落到 ``auto_archive``, 语义上等价于"10 年以内不归档", 没审计价值。
    现在走 ``_validate_int_field`` 的 max_value 兜底, 错误信息含上界值。
    """
    r = diary_tools.diary_archive(weeks_threshold=999999)
    assert r["ok"] is False
    assert "weeks_threshold" in r["error"]
    assert "不能大于" in r["error"]
    assert "520" in r["error"]


def test_diary_archive_rejects_just_above_max(repo_root):
    """边界: 521 (= max + 1) 应该被拒, 520 上一条测试已验证允许。"""
    r = diary_tools.diary_archive(weeks_threshold=521)
    assert r["ok"] is False
    assert "不能大于" in r["error"]
    assert "521" in r["error"]


def test_diary_archive_rejects_bool_threshold(repo_root):
    """bool 是 int 子类但语义上不是数字: ``_validate_int_field`` 显式拒绝。"""
    r_true = diary_tools.diary_archive(weeks_threshold=True)  # type: ignore[arg-type]
    assert r_true["ok"] is False
    assert "weeks_threshold 必须是整数" in r_true["error"]
    assert "bool" in r_true["error"]

    r_false = diary_tools.diary_archive(weeks_threshold=False)  # type: ignore[arg-type]
    assert r_false["ok"] is False
    assert "bool" in r_false["error"]


def test_diary_archive_rejects_non_int_threshold_types(repo_root):
    """非整数类型 (str / float / list / None) 一律拒: 错误信息含实际类型名。"""
    cases = [
        ("5", "str"),
        (5.0, "float"),
        (["2"], "list"),
        (None, "NoneType"),
    ]
    for value, type_name in cases:
        r = diary_tools.diary_archive(weeks_threshold=value)  # type: ignore[arg-type]
        assert r["ok"] is False, f"应拒 {value!r}"
        assert "weeks_threshold 必须是整数" in r["error"]
        assert type_name in r["error"], f"错误信息应含类型 {type_name}: {r['error']!r}"


def test_diary_archive_validation_failure_does_not_call_auto_archive(repo_root, monkeypatch):
    """校验失败时不应触碰 ``auto_archive``: 避免一次没必要的 IO + 污染日志。"""
    from xragent.util import diary_archive as da_mod
    calls: list[tuple[object, object]] = []
    real_auto_archive = da_mod.auto_archive

    def spy(diary_dir, weeks_threshold):
        calls.append((diary_dir, weeks_threshold))
        return real_auto_archive(diary_dir, weeks_threshold)

    monkeypatch.setattr(da_mod, "auto_archive", spy)
    # 也需要 patch tools 里的 import 引用, 否则 diary_tools.diary_archive
    # 调的还是原函数
    monkeypatch.setattr(diary_tools, "auto_archive", spy)

    r = diary_tools.diary_archive(weeks_threshold=999999)
    assert r["ok"] is False
    assert calls == [], f"校验失败不应触发 auto_archive, 但调用了 {calls!r}"


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


# ---------- _validate_int_field helper 单元测试 ----------


def test_validate_int_field_accepts_in_range_value():
    """区间内整数: 返回 ``None`` 表示通过。"""
    from xragent.tools.diary_tools import _validate_int_field
    assert _validate_int_field("x", 5, min_value=0, max_value=10) is None
    # 边界值 (含)
    assert _validate_int_field("x", 0, min_value=0, max_value=10) is None
    assert _validate_int_field("x", 10, min_value=0, max_value=10) is None


def test_validate_int_field_rejects_below_min():
    """小于下界: 错误信息含字段名 + 越界值 + 下界。"""
    from xragent.tools.diary_tools import _validate_int_field
    err = _validate_int_field("foo", -3, min_value=0, max_value=10)
    assert err is not None
    assert "foo" in err
    assert "不能小于" in err
    assert "0" in err
    assert "-3" in err


def test_validate_int_field_rejects_above_max():
    """超过上界: 错误信息含字段名 + 越界值 + 上界。"""
    from xragent.tools.diary_tools import _validate_int_field
    err = _validate_int_field("bar", 999999, min_value=0, max_value=520)
    assert err is not None
    assert "bar" in err
    assert "不能大于" in err
    assert "520" in err
    assert "999999" in err


def test_validate_int_field_rejects_bool_even_though_int_subclass():
    """bool 是 int 子类, 但语义不是数字: 必须显式拒绝。"""
    from xragent.tools.diary_tools import _validate_int_field
    for v in (True, False):
        err = _validate_int_field("flag", v)  # type: ignore[arg-type]
        assert err is not None
        assert "必须是整数" in err
        assert "bool" in err


def test_validate_int_field_rejects_non_int_types():
    """非整数类型 (str / float / list / None / dict) 一律拒。"""
    from xragent.tools.diary_tools import _validate_int_field
    for v, type_name in [("5", "str"), (5.0, "float"), ([2], "list"), (None, "NoneType"), ({}, "dict")]:
        err = _validate_int_field("k", v)  # type: ignore[arg-type]
        assert err is not None, f"应拒 {v!r}"
        assert "必须是整数" in err
        assert type_name in err


def test_validate_int_field_max_value_none_means_no_upper_bound():
    """``max_value=None`` 时不设上限: 任意大整数都通过。"""
    from xragent.tools.diary_tools import _validate_int_field
    assert _validate_int_field("x", 10**18, min_value=0, max_value=None) is None