"""diary archive 工具层契约。

util 层 ``auto_archive`` / ``archive_week`` / ``list_archived_weeks`` 的纯函数
行为已在 ``test_diary_archive.py`` 覆盖；本文件只锁定工具层新增契约：
  * ``diary_auto_archive``：weeks_threshold 非 int 立即被拒（不污染文件）；正常
    路径透传 util，阈值外的周被搬走，阈值内不动
  * ``diary_archive_week``：按 ISO 周名归档，**不看 mtime**（即使本周 daily
    文件 mtime 还在阈值内，仍会被搬走——这是 util 层 archive_week 的固有语义）
  * ``diary_list_archived_weeks``：把 ``[(year, week), ...]`` 转 dict 列表；
    archive/ 不存在时返回空列表
  * 三个工具都被 ``build_default_registry`` 注册：name / risk / input_schema
    与设计一致
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from xragent.tools import diary_tools
from xragent.tools.registry import build_default_registry


# ---------------------------------------------------------------------------
# helpers（与 test_diary_archive.py 解耦，避免共享私有 fixture）
# ---------------------------------------------------------------------------


def _set_mtime(path: Path, target: dt.datetime) -> None:
    ts = target.timestamp()
    os.utime(path, (ts, ts))


def _this_monday() -> dt.date:
    today = dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _make_daily(diary: Path, day: dt.date, body: str = "stub") -> Path:
    p = diary / f"{day.isoformat()}.md"
    p.write_text(f"## stub for {day.isoformat()}\n\n{body}\n", encoding="utf-8")
    return p


def _seed_three_weeks(diary: Path) -> dict[str, Path]:
    """构造 三周样本：this_week / last_week / prev_week（分别 0/7/14 天前）。"""
    monday = _this_monday()
    last_monday = monday - dt.timedelta(days=7)
    prev_monday = monday - dt.timedelta(days=14)
    paths = {
        "this_week": _make_daily(diary, monday, "this week body"),
        "last_week": _make_daily(diary, last_monday, "last week body"),
        "prev_week": _make_daily(diary, prev_monday, "prev week body"),
    }
    noon = dt.time(12, 0, 0)
    _set_mtime(paths["this_week"], dt.datetime.combine(monday, noon))
    _set_mtime(paths["last_week"], dt.datetime.combine(last_monday, noon))
    _set_mtime(paths["prev_week"], dt.datetime.combine(prev_monday, noon))
    return paths


# ---------------------------------------------------------------------------
# diary_auto_archive
# ---------------------------------------------------------------------------


def test_diary_auto_archive_moves_only_out_of_threshold(repo_root: Path) -> None:
    """weeks_threshold=2 时，只归档更早的周（prev_week），this/last_week 不动。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)

    result = diary_tools.diary_auto_archive(weeks_threshold=2)

    assert result["ok"] is True
    assert result["archived"], "阈值外的周应至少有 1 项被归档"
    # 阈值外的 prev_week 已合并到 archive/，原文件被删
    assert not paths["prev_week"].exists()
    assert (diary / "archive").is_dir()
    # 阈值内的 this_week / last_week 原封不动
    assert paths["this_week"].exists()
    assert paths["last_week"].exists()
    # 跳过的应是阈值内的两个文件
    skip_reasons = {s["reason"] for s in result["skipped"]}
    assert "in_threshold" in skip_reasons


def test_diary_auto_archive_rejects_non_int_threshold(repo_root: Path) -> None:
    """weeks_threshold 传字符串：工具层立即拒，不触碰 diary 任何文件。"""
    diary = repo_root / "diary"
    _seed_three_weeks(diary)
    before = sorted(p.name for p in diary.glob("*.md"))

    result = diary_tools.diary_auto_archive(weeks_threshold="two")  # type: ignore[arg-type]

    assert result["ok"] is False
    assert "weeks_threshold" in result["error"]
    assert "str" in result["error"]
    after = sorted(p.name for p in diary.glob("*.md"))
    assert before == after, "失败路径不能动 diary"


def test_diary_auto_archive_rejects_bool_threshold(repo_root: Path) -> None:
    """bool 是 int 的子类，必须显式排除（否则 True/False 会静默通过）。"""
    result = diary_tools.diary_auto_archive(weeks_threshold=True)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "bool" in result["error"]


# ---------------------------------------------------------------------------
# diary_archive_week
# ---------------------------------------------------------------------------


def test_diary_archive_week_overrides_mtime(repo_root: Path) -> None:
    """显式归档本周：mtime 在阈值内也会被搬走（util 层 archive_week 的固有语义）。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)

    today = _this_monday()
    iso_year, iso_week, _ = today.isocalendar()
    result = diary_tools.diary_archive_week(iso_year=iso_year, iso_week=iso_week)

    assert result["ok"] is True
    assert paths["this_week"].name in result["moved_files"]
    assert not paths["this_week"].exists()
    # archive_path 是相对 diary 的 POSIX 路径
    assert result["archive_path"].startswith("archive/")
    assert (diary / result["archive_path"]).is_file()


def test_diary_archive_week_rejects_non_int(repo_root: Path) -> None:
    """iso_week 传字符串：立即拒；iso_year 传字符串同理。"""
    r1 = diary_tools.diary_archive_week(iso_year="2026", iso_week=30)  # type: ignore[arg-type]
    r2 = diary_tools.diary_archive_week(iso_year=2026, iso_week="30")  # type: ignore[arg-type]

    assert r1["ok"] is False and "iso_year" in r1["error"]
    assert r2["ok"] is False and "iso_week" in r2["error"]


# ---------------------------------------------------------------------------
# diary_list_archived_weeks
# ---------------------------------------------------------------------------


def test_diary_list_archived_weeks_empty(repo_root: Path) -> None:
    """archive/ 不存在时返回空列表，不报错。"""
    assert not (repo_root / "diary" / "archive").exists()
    result = diary_tools.diary_list_archived_weeks()
    assert result == {"ok": True, "weeks": []}


def test_diary_list_archived_weeks_reflects_archivals(repo_root: Path) -> None:
    """归档后 list 能看到对应 ISO 周。"""
    diary = repo_root / "diary"
    _seed_three_weeks(diary)
    auto = diary_tools.diary_auto_archive(weeks_threshold=2)
    assert auto["archived"], "前置条件：必须有归档发生"

    result = diary_tools.diary_list_archived_weeks()
    assert result["ok"] is True
    weeks = result["weeks"]
    assert isinstance(weeks, list) and weeks
    for w in weeks:
        assert set(w.keys()) == {"iso_year", "iso_week"}
        assert isinstance(w["iso_year"], int)
        assert isinstance(w["iso_week"], int)
    # 顺序：按 (year, week) 升序
    assert weeks == sorted(weeks, key=lambda x: (x["iso_year"], x["iso_week"]))


# ---------------------------------------------------------------------------
# registry 暴露
# ---------------------------------------------------------------------------


def test_archive_tools_visible_via_build_default_registry(repo_root: Path) -> None:
    """build_default_registry 暴露三个工具，且 risk / schema 与设计一致。"""
    r = build_default_registry()
    names = set(r.names())

    # 名字必须出现
    assert {"diary_auto_archive", "diary_archive_week", "diary_list_archived_weeks"} <= names

    # risk 等级
    assert r.get("diary_auto_archive").risk == "medium"
    assert r.get("diary_archive_week").risk == "medium"
    assert r.get("diary_list_archived_weeks").risk == "low"

    # schema 必填字段
    auto_schema = r.get("diary_auto_archive").input_schema
    assert auto_schema["properties"]["weeks_threshold"]["default"] == 2
    assert auto_schema["properties"]["weeks_threshold"]["minimum"] == 0

    week_schema = r.get("diary_archive_week").input_schema
    assert set(week_schema["required"]) == {"iso_year", "iso_week"}
    assert week_schema["properties"]["iso_week"]["maximum"] == 53

    # list 工具无 required
    assert r.get("diary_list_archived_weeks").input_schema.get("required", []) == []


def test_registry_run_archive_tools_low_risk_no_gate(repo_root: Path) -> None:
    """low risk 工具（list_archived_weeks）走 registry.run 不需要 gate。

    medium risk 工具（auto_archive）即使没 gate 也会被执行（gate=None 时
    _apply_hitl 走直通分支），但需要确认调用方不会被 HITL 卡住。
    """
    r = build_default_registry()

    # low risk: 无需 gate，直接调通
    out = r.run("diary_list_archived_weeks", {})
    assert out["ok"] is True
    assert "blocked_by" not in out

    # medium risk + gate=None: 透传执行（无审批），handler 报错才返回 ok=False
    _seed_three_weeks(repo_root / "diary")
    out2 = r.run("diary_auto_archive", {"weeks_threshold": 2})
    assert out2["ok"] is True
    assert "blocked_by" not in out2