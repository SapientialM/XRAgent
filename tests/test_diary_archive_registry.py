"""diary_archive 工具的注册表契约 + 端到端校验。

既有 test_diary_archive.py 覆盖纯函数行为(parse_daily_filename /
auto_archive / archive_week / list_archived_weeks)。
本文件专门覆盖"作为 ToolRegistry 中的工具"这一层契约:

  * build_default_registry() 必须把 diary_archive 登记进去
  * ToolDef 的字段(name / risk / handler / schema)正确
  * JSON Schema 自洽(类型、required、范围)
  * 通过 ToolRegistry.run("diary_archive", args, gate=None) 端到端跑通
    - happy path: 旧文件被归档到 diary/archive/
    - validation: 负数 / 超过 520 应返回 ok=False, 不抛异常
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

import xragent.tools.registry as registry_mod
from xragent.tools.registry import ToolRegistry, build_default_registry


# ---------------------------------------------------------------------------
# 注册表契约
# ---------------------------------------------------------------------------


def test_build_default_registry_includes_diary_archive():
    """build_default_registry() 出来的 registry 一定要有 diary_archive。"""
    r = build_default_registry()
    assert "diary_archive" in r.names()


def test_diary_archive_spec_fields_are_correct():
    """ToolDef 的 name / risk / handler / schema 都对得上。"""
    r = build_default_registry()
    specs = {s.name: s for s in r.specs()}
    assert "diary_archive" in specs

    spec = specs["diary_archive"]
    assert spec.name == "diary_archive"
    # 纯函数 + 写入本地 archive/, 视为 low risk
    assert spec.risk == "low"
    # handler 必须是真实的 diary_tools.diary_archive
    from xragent.tools import diary_tools
    assert spec.handler is diary_tools.diary_archive
    # 描述里要提到 "weeks_threshold" 或 "周"
    assert "周" in spec.description or "weeks_threshold" in spec.description


def test_diary_archive_schema_is_well_formed_json_schema():
    """JSON Schema: weeks_threshold integer, required, [0, 520]。"""
    r = build_default_registry()
    spec = r.specs()[r.names().index("diary_archive")]
    schema = spec.parameters

    assert isinstance(schema, dict)
    assert schema.get("type") == "object"

    props = schema.get("properties", {})
    assert "weeks_threshold" in props, "schema 必须声明 weeks_threshold"

    wt = props["weeks_threshold"]
    # 类型必须是 integer / number(允许 integer)
    assert wt.get("type") in ("integer", "number")
    # 范围边界
    assert wt.get("minimum") == 0
    assert wt.get("maximum") == 520
    # 默认值 2
    assert wt.get("default") == 2

    # required: 不能让 weeks_threshold 缺失
    required = set(schema.get("required", []))
    assert "weeks_threshold" in required


# ---------------------------------------------------------------------------
# ToolRegistry.run 端到端: happy path
# ---------------------------------------------------------------------------


def test_run_diary_archive_end_to_end_archives_old_weeks(repo_root):
    """走 registry.run 而不是直接调函数,验证 registry 桥接正确。"""
    diary = repo_root / "diary"

    # 准备 3 周样本(本周 / 上周 / 上上周)
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    last_monday = monday - dt.timedelta(days=7)
    prev_monday = monday - dt.timedelta(days=14)

    files = {}
    noon = dt.time(12, 0, 0)
    for label, day in [("this_week", monday), ("last_week", last_monday), ("prev_week", prev_monday)]:
        p = diary / f"{day.isoformat()}.md"
        p.write_text(f"## stub {label}\nbody for {label}\n", encoding="utf-8")
        os.utime(p, (dt.datetime.combine(day, noon).timestamp(),) * 2)
        files[label] = p

    # 端到端走 registry
    r = build_default_registry()
    result = r.run("diary_archive", {"weeks_threshold": 2}, gate=None)

    assert result.get("ok") is True, f"diary_archive 应成功, 实际 {result}"

    # 上上周被归档
    prev_iso = dt.date.fromtimestamp(files["prev_week"].stat().st_mtime).isocalendar()
    expected_archive = diary / "archive" / f"{prev_iso[0]}-W{prev_iso[1]:02d}.md"
    assert expected_archive.exists(), f"archive 文件应存在: {expected_archive}"
    assert not files["prev_week"].exists(), "上上周原文件应被删"

    # 本周 / 上周原封不动
    assert files["this_week"].exists()
    assert files["last_week"].exists()

    # 归档结果里至少有一个 archived 条目
    archived = result.get("archived", [])
    assert len(archived) >= 1
    assert any(a.get("iso_week") == prev_iso[1] for a in archived)


def test_run_diary_archive_with_weeks_threshold_zero_keeps_only_this_week(repo_root):
    """weeks_threshold=0: 仅本周保留, 其它全归档。"""
    diary = repo_root / "diary"
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    last_monday = monday - dt.timedelta(days=7)

    p_this = diary / f"{monday.isoformat()}.md"
    p_last = diary / f"{last_monday.isoformat()}.md"
    noon = dt.time(12, 0, 0)
    for p, day in [(p_this, monday), (p_last, last_monday)]:
        p.write_text(f"body {p.name}\n", encoding="utf-8")
        os.utime(p, (dt.datetime.combine(day, noon).timestamp(),) * 2)

    r = build_default_registry()
    result = r.run("diary_archive", {"weeks_threshold": 0}, gate=None)
    assert result.get("ok") is True

    # 本周保留
    assert p_this.exists()
    # 上周被归档 → archive/ 里出现
    last_iso = dt.date.fromtimestamp(p_last.stat().st_mtime).isocalendar()
    expected_archive = diary / "archive" / f"{last_iso[0]}-W{last_iso[1]:02d}.md"
    assert expected_archive.exists()
    # 注:上周原文件已被删
    assert not p_last.exists()


# ---------------------------------------------------------------------------
# ToolRegistry.run 端到端: validation / 错误路径
# ---------------------------------------------------------------------------


def test_run_diary_archive_negative_threshold_returns_ok_false(repo_root):
    """负数应被 schema 拒绝 → ok=False 且不抛异常。"""
    r = build_default_registry()
    # 故意不造样本数据;validation 失败应先于实际扫描
    result = r.run("diary_archive", {"weeks_threshold": -1}, gate=None)
    assert result.get("ok") is False
    # 不应留下 archive 目录(就算没造样本,也确保扫描未发生)
    assert not (repo_root / "diary" / "archive").exists()


def test_run_diary_archive_exceeds_max_returns_ok_false(repo_root):
    """超过 520 周上限 → ok=False。"""
    r = build_default_registry()
    result = r.run("diary_archive", {"weeks_threshold": 9999}, gate=None)
    assert result.get("ok") is False


# ---------------------------------------------------------------------------
# 直接调 handler 与通过 registry 调 等价性(可选 sanity)
# ---------------------------------------------------------------------------


def test_registry_handler_identity_matches_module_attr():
    """spec.handler 必须就是 xragent.tools.diary_tools.diary_archive。"""
    r = build_default_registry()
    spec = r.specs()[r.names().index("diary_archive")]
    from xragent.tools import diary_tools
    # 同对象(id 一致),不是 wrapper / 拷贝
    assert spec.handler is diary_tools.diary_archive
    # module 的 __name__ 也是 diary_archive,避免 monkey-patch 之类问题
    assert diary_tools.diary_archive.__name__ == "diary_archive"


def test_registry_module_exports_diary_archive():
    """xragent.tools.diary_tools 这个模块本身要导出 diary_archive。"""
    from xragent.tools import diary_tools
    assert hasattr(diary_tools, "diary_archive")
    assert callable(diary_tools.diary_archive)