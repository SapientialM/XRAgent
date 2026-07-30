"""diary_archive 的真实归档行为测试（旧 mtime 文件 → archive/）。"""
from __future__ import annotations

import os
import time

import pytest

from xragent.tools import diary_tools
from xragent.config.settings import get_settings


def _set_mtime_to_now(path):
    """把文件 mtime 设回 1 年前，触发归档。"""
    old = time.time() - 365 * 24 * 3600
    os.utime(path, (old, old))


def test_diary_archive_moves_old_files_to_archive(repo_root):
    """mtime 落在阈值外的 daily 文件被合并到 diary/archive/{iso_year}-W{iso_week}.md 并删除原文件。"""
    diary_dir = repo_root / "diary"

    # 在 1 年前写入两条 diary（mtime 用 os.utime 强制覆盖）
    f1 = diary_dir / "2020-01-08.md"
    f2 = diary_dir / "2020-01-09.md"
    f1.write_text("# diary_tools d1\n", encoding="utf-8")
    f2.write_text("# diary_tools d2\n", encoding="utf-8")
    _set_mtime_to_now(f1)
    _set_mtime_to_now(f2)

    # 阈值 = 2 周：旧文件肯定在阈值外
    r = diary_tools.diary_archive(weeks_threshold=2)

    assert r["ok"] is True
    # 两条都该被归档
    archived_paths = r["archived"]
    assert len(archived_paths) == 2
    assert any("2020-01-08.md" in p for p in archived_paths)
    assert any("2020-01-09.md" in p for p in archived_paths)

    # 原文件已删除
    assert not f1.exists(), f"原文件未被删除: {f1}"
    assert not f2.exists(), f"原文件未被删除: {f2}"

    # archive/{iso_year}-W{iso_week}.md 出现，包含两条内容
    archive_dir = diary_dir / "archive"
    assert archive_dir.exists(), "archive 子目录未创建"
    week_files = list(archive_dir.glob("*-W*.md"))
    assert len(week_files) == 1, f"应为同一周，预期 1 个文件，实际 {len(week_files)}"
    body = week_files[0].read_text(encoding="utf-8")
    assert "d1" in body and "d2" in body, f"归档文件丢失内容: {body!r}"


def test_diary_archive_keeps_recent_files(repo_root):
    """今天写入的文件（mtime = now）属于本周，阈值=2 时不应被归档。"""
    diary_dir = repo_root / "diary"

    today_name = time.strftime("%Y-%m-%d")
    today = diary_dir / f"{today_name}.md"
    today.write_text("# today\n", encoding="utf-8")
    # mtime 就是刚才写入时的时间，本周内

    r = diary_tools.diary_archive(weeks_threshold=2)

    assert r["ok"] is True
    assert today.exists(), "本周内文件不应被归档"
    # 不应在 archived 列表里
    assert not any(today_name in p for p in r["archived"])
    # 应该在 skipped 里，原因是 in_threshold
    skipped_reasons = [s["reason"] for s in r["skipped"]]
    assert "in_threshold" in skipped_reasons


def test_diary_archive_is_idempotent(repo_root):
    """连续跑两次 diary_archive：第二次应无新归档（不重复处理）。"""
    diary_dir = repo_root / "diary"

    f = diary_dir / "2019-12-25.md"
    f.write_text("# old xmas\n", encoding="utf-8")
    _set_mtime_to_now(f)

    r1 = diary_tools.diary_archive(weeks_threshold=2)
    assert len(r1["archived"]) == 1

    r2 = diary_tools.diary_archive(weeks_threshold=2)
    assert r2["archived"] == [], f"第二次应无新归档，实际: {r2['archived']}"


def test_diary_archive_settings_path_independence(repo_root):
    """diary_archive 走 settings.diary_dir，不接受外部路径——用 monkeypatch 改 settings 后能看到。"""
    from pathlib import Path
    import tempfile

    # 另建一个 diary 目录并通过 monkeypatch 指向它
    other = Path(tempfile.mkdtemp()) / "diary"
    other.mkdir(parents=True)
    old_file = other / "2018-06-15.md"
    old_file.write_text("# other x\n", encoding="utf-8")
    _set_mtime_to_now(old_file)

    s = get_settings()
    orig = s.diary_dir
    s.diary_dir = other
    try:
        r = diary_tools.diary_archive(weeks_threshold=2)
    finally:
        s.diary_dir = orig

    assert r["ok"] is True
    assert len(r["archived"]) == 1
    assert not old_file.exists()
    # 新归档目录在 other 下
    assert (other / "archive").exists()