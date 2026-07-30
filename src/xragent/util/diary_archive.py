"""按周归档 diary/*.md。

## 为什么

diary/ 下的 `YYYY-MM-DD.md` 会一直膨胀（每天一条，几个 turn 就能写出
几十 KB）。若不归档，长期看会拖累 `git status` / `git add -A` 性能、
PR review 时噪声大。归档按 ISO 周合并到 `diary/archive/YYYY-Wxx.md`，
原 daily 文件被删除,既保留历史又让当前 diary/ 保持精简。

## 边界

- 跳过 diary/search-log.md（搜索日志、机器生成,不是日记正文）
- 跳过 diary/turns/（结构化日志,另有写入白名单护栏)
- 跳过 diary/archive/ 自身（递归会污染归档结果)
- 跳过 N 周阈值内（含本周)的日记（默认 N=2,保留本周 + 上周 + 上上周的完整周)
  → Agent 本周 / 上周仍可直接 ls 到今天的日记。
- 仅归档文件名严格匹配 `YYYY-MM-DD.md` 的文件（其它意外落地的临时文件不动）。

## API

- archive_week(diary_dir, iso_year, iso_week) -> dict
    把指定 ISO 周的所有 daily 文件合并到 archive/{year}-W{week:02d}.md 并删除原文件。
    返回 {ok, archive_path, moved_files[], appended_sections[]}

- auto_archive(diary_dir, weeks_threshold=2) -> dict
    按 mtime 自动归档 N 周前的所有完整周。返回 {ok, archived[], skipped[]}
    archived[i] = {iso_year, iso_week, archive_path, moved_files[]}
    skipped[i]  = {"file": ..., "reason": ...}

- list_archived_weeks(diary_dir) -> list[tuple[int, int]]
    列出 archive/ 下所有已归档的 (iso_year, iso_week)，按 (year, week) 升序。
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

# 严格匹配 daily 文件名 `YYYY-MM-DD.md`;search-log.md / turns/ 等不动。
_DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")

# 归档文件名里的 ISO 周号宽度(2 位)。
_ARCHIVE_NAME_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")


def _today_iso() -> tuple[int, int]:
    """返回 (iso_year, iso_week) of today."""
    y, w, _ = dt.date.today().isocalendar()
    return y, w


def _week_bounds(iso_year: int, iso_week: int) -> tuple[dt.date, dt.date]:
    """ISO 周(年, 周号) -> [周一, 周日] 日期范围。"""
    monday = dt.date.fromisocalendar(iso_year, iso_week, 1)
    sunday = dt.date.fromisocalendar(iso_year, iso_week, 7)
    return monday, sunday


def _is_in_or_after_threshold(today: dt.date, file_monday: dt.date, weeks_threshold: int) -> bool:
    """判断 file_monday 是否位于"今天所在周的 N 周阈值内"(含)。

    weeks_threshold=2 时：今天所在周、上周、上上周都保留;更早的周会被归档。
    实现：delta_weeks = (today_monday - file_monday) / 7 天;若 <= weeks_threshold 则保留。
    """
    today_monday = today - dt.timedelta(days=today.weekday())
    delta_days = (today_monday - file_monday).days
    return 0 <= delta_days <= weeks_threshold * 7


def parse_daily_filename(path: Path) -> dt.date | None:
    """`2026-07-30.md` -> date(2026,7,30);其它文件名返回 None。"""
    m = _DAILY_RE.match(path.name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def archive_week(diary_dir: Path, iso_year: int, iso_week: int) -> dict:
    """把指定 ISO 周的所有 daily 文件合并到 archive/{year}-W{week:02d}.md。

    合并语义: 若 archive 文件已存在,新内容追加在末尾;若不存在,新建。
    归档文件的结构: 顶部一行 `# Week {year}-W{week:02d}` 标题,之后按日期升序
    排列,每天的 daily 文件完整内容作为 `## [{date}]` 子节追加。

    返回:
        ok: bool
        archive_path: str (相对 diary_dir 的 POSIX 路径)
        moved_files: list[str] (被删除的原 daily 文件名)
        appended_sections: list[str] (实际追加的日期子节, YYYY-MM-DD 形式)
    """
    diary_dir = Path(diary_dir)
    if not diary_dir.is_dir():
        return {"ok": False, "error": f"diary_dir 不存在: {diary_dir}"}

    monday, sunday = _week_bounds(iso_year, iso_week)
    # 在目录里找这一周内的 daily 文件(周一到周日,含两端)
    in_week: list[tuple[dt.date, Path]] = []
    for entry in sorted(diary_dir.iterdir()):
        if not entry.is_file():
            continue
        d = parse_daily_filename(entry)
        if d is None:
            continue
        if monday <= d <= sunday:
            in_week.append((d, entry))

    if not in_week:
        return {
            "ok": True,
            "archive_path": "",
            "moved_files": [],
            "appended_sections": [],
            "note": f"周 {iso_year}-W{iso_week:02d} 没有 daily 文件",
        }

    archive_dir = diary_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"{iso_year}-W{iso_week:02d}.md"

    # 已存在的归档文件: 读出现有内容后追加;否则新建时加周标题。
    new_block_parts: list[str] = []
    if not archive_path.exists():
        new_block_parts.append(f"# Week {iso_year}-W{iso_week:02d}\n")
    else:
        new_block_parts.append("\n")

    moved_files: list[str] = []
    appended_sections: list[str] = []
    for d, path in sorted(in_week, key=lambda x: x[0]):
        body = path.read_text(encoding="utf-8")
        # 去掉 daily 文件首部的空行(若整篇都是空,body 可能是 ""),统一成
        # `## [YYYY-MM-DD]\n\n{body.rstrip()}\n` 子节。
        new_block_parts.append(f"## [{d.isoformat()}]\n\n{body.rstrip()}\n")
        moved_files.append(path.name)
        appended_sections.append(d.isoformat())

    # 一次性写入(追加模式 'a');避免多次 open()。
    with archive_path.open("a", encoding="utf-8") as f:
        f.write("".join(new_block_parts))

    # 删除原 daily 文件(已合并到 archive)。
    for _, path in in_week:
        try:
            path.unlink()
        except OSError as e:
            # 单个文件删不掉不应阻塞其它;返回 ok=False + error 即可。
            return {
                "ok": False,
                "error": f"删除原文件失败 {path.name}: {e}",
                "archive_path": archive_path.relative_to(diary_dir).as_posix(),
                "moved_files": moved_files,
                "appended_sections": appended_sections,
            }

    return {
        "ok": True,
        "archive_path": archive_path.relative_to(diary_dir).as_posix(),
        "moved_files": moved_files,
        "appended_sections": appended_sections,
    }


def auto_archive(diary_dir: Path, weeks_threshold: int = 2) -> dict:
    """按 mtime 自动归档 N 周阈值外的所有 daily 文件。

    weeks_threshold=2 (默认): 保留今天所在周、上周、上上周;更早的完整周全部归档。

    skipped 列表里给出未归档的文件 + 原因:
      - "in_threshold": 文件所在周在阈值内(本周 / 上周 / 上上周)
      - "no_iso_week": 文件 mtime 解析不出 ISO 周(理论上不应发生)
      - "parse_failed": 文件名不是 YYYY-MM-DD.md 格式
    """
    diary_dir = Path(diary_dir)
    if not diary_dir.is_dir():
        return {"ok": False, "error": f"diary_dir 不存在: {diary_dir}"}

    today = dt.date.today()
    seen_weeks: set[tuple[int, int]] = set()
    archived: list[dict] = []
    skipped: list[dict] = []

    for entry in sorted(diary_dir.iterdir()):
        if not entry.is_file():
            continue
        d = parse_daily_filename(entry)
        if d is None:
            skipped.append({"file": entry.name, "reason": "parse_failed"})
            continue
        # 文件名 vs mtime: 优先用 mtime 决定"是不是阈值内的周"。
        # 这样即使 daily 文件名是今天的、但 mtime 显示是上周落地的,也会按 mtime 归档。
        try:
            stat = entry.stat()
            mtime = dt.date.fromtimestamp(stat.st_mtime)
        except OSError:
            skipped.append({"file": entry.name, "reason": "stat_failed"})
            continue

        try:
            iso = mtime.isocalendar()
        except Exception:  # pragma: no cover - 极少触发
            skipped.append({"file": entry.name, "reason": "no_iso_week"})
            continue

        file_monday = mtime - dt.timedelta(days=mtime.weekday())
        if _is_in_or_after_threshold(today, file_monday, weeks_threshold):
            skipped.append({"file": entry.name, "reason": "in_threshold"})
            continue

        key = (iso[0], iso[1])
        if key in seen_weeks:
            # 同周已归档过(可能上一轮已处理过,或文件按 ISO 周撞了)
            continue
        seen_weeks.add(key)

        r = archive_week(diary_dir, iso[0], iso[1])
        if r.get("ok"):
            archived.append(
                {
                    "iso_year": iso[0],
                    "iso_week": iso[1],
                    "archive_path": r.get("archive_path", ""),
                    "moved_files": r.get("moved_files", []),
                }
            )
        else:
            skipped.append({"file": entry.name, "reason": r.get("error", "unknown")})

    return {"ok": True, "archived": archived, "skipped": skipped}


def list_archived_weeks(diary_dir: Path) -> list[tuple[int, int]]:
    """列出 archive/ 下已归档的 (iso_year, iso_week),按 (year, week) 升序。"""
    diary_dir = Path(diary_dir)
    archive_dir = diary_dir / "archive"
    if not archive_dir.is_dir():
        return []
    out: list[tuple[int, int]] = []
    for entry in archive_dir.iterdir():
        if not entry.is_file():
            continue
        m = _ARCHIVE_NAME_RE.match(entry.name)
        if not m:
            continue
        out.append((int(m.group(1)), int(m.group(2))))
    out.sort()
    return out


__all__ = [
    "archive_week",
    "auto_archive",
    "list_archived_weeks",
    "parse_daily_filename",
]