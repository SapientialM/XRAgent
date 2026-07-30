"""按周归档 diary 的单测。

每个测试跑在 conftest 的 repo_root(tmp_path) 里,通过 mtime 显式构造
"今天所在周 / 上周 / 上上周"三档样本,验证:
  - 阈值外(默认 2 周前之前)的周被合并到 archive/ 并删除原文件
  - 阈值内的周原封不动
  - search-log.md / turns/ 不被动
  - 同周多次调 auto_archive 幂等
  - archive_week 显式归档指定 ISO 周
  - parse_daily_filename 边界(非法文件名返回 None)
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from xragent.util.diary_archive import (
    archive_week,
    auto_archive,
    list_archived_weeks,
    parse_daily_filename,
)


def _set_mtime(path: Path, target: dt.datetime) -> None:
    """显式设 mtime(秒精度)。"""
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
    """在 diary/ 下种三周样本:
        - this_week:  本周一 (mtime=今天)
        - last_week:  上周一     (mtime=7 天前)
        - prev_week:  上上周一   (mtime=14 天前,默认阈值下应被归档)
    返回 {label: path}。"""
    monday = _this_monday()
    last_monday = monday - dt.timedelta(days=7)
    prev_monday = monday - dt.timedelta(days=14)

    paths = {
        "this_week": _make_daily(diary, monday, "this week body"),
        "last_week": _make_daily(diary, last_monday, "last week body"),
        "prev_week": _make_daily(diary, prev_monday, "prev week body"),
    }

    # mtime 设到对应周一的中午,避免跨日误差。
    noon = dt.time(12, 0, 0)
    _set_mtime(paths["this_week"], dt.datetime.combine(monday, noon))
    _set_mtime(paths["last_week"], dt.datetime.combine(last_monday, noon))
    _set_mtime(paths["prev_week"], dt.datetime.combine(prev_monday, noon))
    return paths


# ---------------------------------------------------------------------------
# parse_daily_filename
# ---------------------------------------------------------------------------


def test_parse_daily_filename_happy():
    assert parse_daily_filename(Path("2026-07-30.md")) == dt.date(2026, 7, 30)


def test_parse_daily_filename_rejects_non_matching():
    assert parse_daily_filename(Path("search-log.md")) is None
    assert parse_daily_filename(Path("turns")) is None  # 目录
    assert parse_daily_filename(Path("2026-7-30.md")) is None  # 月日未补零
    assert parse_daily_filename(Path("2026-13-01.md")) is None  # 非法日期
    assert parse_daily_filename(Path("2026-07-30.txt")) is None  # 后缀错


# ---------------------------------------------------------------------------
# archive_week: 显式归档指定 ISO 周
# ---------------------------------------------------------------------------


def test_archive_week_merges_into_archive_file(repo_root):
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)
    prev_path = paths["prev_week"]
    prev_iso = prev_path.stat().st_mtime and dt.date.fromtimestamp(prev_path.stat().st_mtime).isocalendar()
    iso_year, iso_week, _ = prev_iso

    r = archive_week(diary, iso_year, iso_week)
    assert r["ok"] is True
    assert r["moved_files"] == [prev_path.name]
    assert prev_path.name in r["appended_sections"][0]

    # 原文件被删
    assert not prev_path.exists()

    # archive 文件被建出来,内容含 daily body
    archive_path = diary / "archive" / f"{iso_year}-W{iso_week:02d}.md"
    assert archive_path.exists()
    body = archive_path.read_text(encoding="utf-8")
    assert "prev week body" in body
    assert f"## [{prev_path.name[:10]}]" in body


def test_archive_week_is_idempotent_on_repeated_call(repo_root):
    """第一次归档后原文件已删,再调同 ISO 周应返回 ok=True 且 moved_files=空。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)
    prev_path = paths["prev_week"]
    prev_iso = dt.date.fromtimestamp(prev_path.stat().st_mtime).isocalendar()
    iso_year, iso_week, _ = prev_iso

    r1 = archive_week(diary, iso_year, iso_week)
    assert r1["ok"] is True
    assert len(r1["moved_files"]) == 1

    r2 = archive_week(diary, iso_year, iso_week)
    assert r2["ok"] is True
    assert r2["moved_files"] == []
    assert r2["note"].startswith("周 ")


# ---------------------------------------------------------------------------
# auto_archive: 阈值行为
# ---------------------------------------------------------------------------


def test_auto_archive_archives_only_threshold_exceeded(repo_root):
    """默认阈值 2 周:上上周(>= 14 天前)被归档,本周 / 上周不动。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)
    prev_path = paths["prev_week"]

    r = auto_archive(diary)  # 默认 weeks_threshold=2
    assert r["ok"] is True

    # 上上周被归档
    prev_iso = dt.date.fromtimestamp(prev_path.stat.st_mtime if hasattr(prev_path.stat(), "st_mtime") else prev_path.stat().st_mtime).isocalendar() if False else dt.date.fromtimestamp(prev_path.stat().st_mtime).isocalendar()
    expected_archive = diary / "archive" / f"{prev_iso[0]}-W{prev_iso[1]:02d}.md"
    assert expected_archive.exists()

    # 上上周原文件被删
    assert not prev_path.exists()

    # 本周 / 上周原封不动
    assert paths["this_week"].exists()
    assert paths["last_week"].exists()

    # 至少有一条 archived 记录(关于上上周)
    archived_weeks = {a["iso_week"] for a in r["archived"]}
    assert prev_iso[1] in archived_weeks
    # 本周和上周应在 skipped 里
    skipped_files = {s["file"] for s in r["skipped"]}
    assert paths["this_week"].name in skipped_files
    assert paths["last_week"].name in skipped_files


def test_auto_archive_skips_search_log_and_turns_dir(repo_root):
    """search-log.md 和 turns/ 内的文件不应被归档。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)

    # 准备 search-log.md (放旧 mtime 也不该动)
    search_log = diary / "search-log.md"
    search_log.write_text("search history", encoding="utf-8")
    old_mtime = dt.datetime.combine(_this_monday() - dt.timedelta(days=60), dt.time(12, 0))
    _set_mtime(search_log, old_mtime)

    # 准备 turns/ 内的文件 (同样放旧 mtime)
    turn_file = diary / "turns" / "turn-2026-01-01.json"
    turn_file.write_text("{}", encoding="utf-8")
    _set_mtime(turn_file, old_mtime)

    r = auto_archive(diary)
    assert r["ok"] is True

    # search-log.md 必须在原位
    assert search_log.exists()
    assert search_log.read_text(encoding="utf-8") == "search history"

    # turns/ 内文件必须在原位
    assert turn_file.exists()

    # archive/ 里不能出现 search-log.md 或 turns/ 内容
    archive_dir = diary / "archive"
    if archive_dir.exists():
        for p in archive_dir.rglob("*"):
            if p.is_file():
                content = p.read_text(encoding="utf-8", errors="ignore")
                assert "search history" not in content
                assert p.name != "search-log.md"


def test_auto_archive_idempotent_when_run_twice(repo_root):
    """跑完第一次后再跑一次:archived 应为空(阈值外的周已删),其它文件不动。"""
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)

    r1 = auto_archive(diary)
    assert any(a["iso_week"] for a in r1["archived"])  # 至少归档了 1 周

    # 记录所有原文件 + archive 内容的快照
    this_week_before = paths["this_week"].read_text(encoding="utf-8")
    last_week_before = paths["last_week"].read_text(encoding="utf-8")

    r2 = auto_archive(diary)
    assert r2["ok"] is True
    # 第二次:阈值外已无文件,archived 应空
    assert r2["archived"] == []

    # 本周 / 上周内容未变
    assert paths["this_week"].read_text(encoding="utf-8") == this_week_before
    assert paths["last_week"].read_text(encoding="utf-8") == last_week_before


# ---------------------------------------------------------------------------
# list_archived_weeks
# ---------------------------------------------------------------------------


def test_list_archived_weeks_returns_sorted(repo_root):
    diary = repo_root / "diary"
    paths = _seed_three_weeks(diary)

    auto_archive(diary, weeks_threshold=0)  # 强制归档所有非本周的周
    weeks = list_archived_weeks(diary)
    # 应至少有 2 个 (上周 + 上上周);按 (year, week) 升序
    assert len(weeks) >= 2
    assert weeks == sorted(weeks)
    # 元素是 (int, int) 二元组
    for y, w in weeks:
        assert isinstance(y, int)
        assert isinstance(w, int)


def test_list_archived_weeks_empty_when_no_archive_dir(repo_root):
    diary = repo_root / "diary"
    # 没有 archive/ 子目录时,返回空列表(不抛异常)
    assert list_archived_weeks(diary) == []