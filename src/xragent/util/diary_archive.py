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

**typing (本轮)**: 把 ``_today_iso`` / ``_week_bounds`` / ``_unlink_files`` /
``parse_daily_filename`` 的 docstring 从单行/中文散写改成 Google-style (Args /
Returns)。``archive_week`` / ``auto_archive`` 保留 ``dict`` 返回类型（避免改
调用方），但在 docstring 里把 dict schema 写明。``list_archived_weeks`` 的
返回类型补 PEP 604 ``list[tuple[int, int]]`` 注解（原本 docstring 里有但
签名缺）。
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

# 严格匹配 daily 文件名 `YYYY-MM-DD.md`;search-log.md / turns/ 等不动。
_DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")

# 归档文件名里的 ISO 周号宽度(2 位)。
_ARCHIVE_NAME_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")


def _monday_of(d: dt.date) -> dt.date:
    """返回 d 所在 ISO 周的周一(以 date.weekday()=0 为基准)。

    原代码在 ``_within_weeks_threshold`` 和 ``auto_archive`` 两处都 inline
    ``d - dt.timedelta(days=d.weekday())``；抽到这里去重后,这两处只需
    ``_monday_of(today)`` / ``_monday_of(mtime)``,意图也更直白。

    Args:
        d: 任意 ``datetime.date``。

    Returns:
        d 所在 ISO 周的周一日期。
    """
    return d - dt.timedelta(days=d.weekday())


def _today_iso() -> tuple[int, int]:
    """取今天所在的 ISO (年, 周号)。

    Returns:
        ``(iso_year, iso_week)`` —— ``dt.date.today().isocalendar()`` 的前两位。
    """
    y, w, _ = dt.date.today().isocalendar()
    return y, w


def _week_bounds(iso_year: int, iso_week: int) -> tuple[dt.date, dt.date]:
    """ISO 周(年, 周号) → [周一, 周日] 日期范围。

    Args:
        iso_year: ISO 周所在的年份（注意：跨年周可能属于前一年的 ISO 周）。
        iso_week: ISO 周号（1–53）。

    Returns:
        ``(monday, sunday)`` —— 该 ISO 周的周一和周日 ``datetime.date``。
    """
    monday = dt.date.fromisocalendar(iso_year, iso_week, 1)
    sunday = dt.date.fromisocalendar(iso_year, iso_week, 7)
    return monday, sunday


def _within_weeks_threshold(today: dt.date, file_monday: dt.date, weeks_threshold: int) -> bool:
    """判断 file_monday 是否位于"今天所在周的 N 周阈值内"(含)。

    weeks_threshold=2 时：今天所在周、上周、上上周都保留;更早的周会被归档。
    实现：delta_weeks = (today_monday - file_monday) / 7 天;若 <= weeks_threshold 则保留。

    Args:
        today: 今天日期（通常 ``dt.date.today()``）。
        file_monday: 文件所在 ISO 周的周一（来自 ``_monday_of(mtime)``）。
        weeks_threshold: 阈值周数；0 表示"仅本周"，更大值更宽松。

    Returns:
        True = 在阈值内（保留），False = 应归档。
    """
    delta_days = (_monday_of(today) - file_monday).days
    return 0 <= delta_days <= weeks_threshold * 7


def parse_daily_filename(path: Path) -> dt.date | None:
    """把 ``YYYY-MM-DD.md`` 文件名解析成 ``datetime.date``。

    Args:
        path: 文件路径；只读 ``path.name``，不看父目录。

    Returns:
        解析成功返回 ``datetime.date``；文件名不匹配、或月/日越界（如
        ``2026-02-30.md``）返回 ``None``。
    """
    m = _DAILY_RE.match(path.name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _unlink_files(paths: list[Path]) -> str | None:
    """逐个 ``Path.unlink()``；任一失败返回错误消息，全成功返回 ``None``。

    Args:
        paths: 要删除的文件路径列表（通常来自 ``archive_week`` 收集的 daily 列表）。

    Returns:
        ``None`` = 全部删除成功；非空字符串 = 第一个失败的错误消息
        （格式 ``"删除原文件失败 {name}: {err}"``），后续文件不再尝试。
    """
    for path in paths:
        try:
            path.unlink()
        except OSError as e:
            return f"删除原文件失败 {path.name}: {e}"
    return None


def archive_week(diary_dir: Path, iso_year: int, iso_week: int) -> dict:
    """把指定 ISO 周的所有 daily 文件合并到 archive/{year}-W{week:02d}.md。

    合并语义: 若 archive 文件已存在,新内容追加在末尾;若不存在,新建。
    归档文件的结构: 顶部一行 `# Week {year}-W{week:02d}` 标题,之后按日期升序
    排列,每天的 daily 文件完整内容作为 `## [{date}]` 子节追加。

    Args:
        diary_dir: diary 根目录路径（不是 archive 子目录）。
        iso_year: 目标 ISO 周的年份。
        iso_week: 目标 ISO 周的周号（1–53）。

    Returns:
        ``dict``，schema（成功时）::

            {
                "ok": True,
                "archive_path": "archive/2026-W30.md",  # 相对 diary_dir 的 POSIX 路径
                "moved_files": ["2026-07-27.md", ...],  # 被删除的原 daily 文件名
                "appended_sections": ["2026-07-27", ...],  # 实际追加的日期
            }

        失败时（含 ``"ok": False``）::

            {"ok": False, "error": "...", "archive_path": "...",
             "moved_files": [...], "appended_sections": [...]}

        无 daily 文件的周返回::

            {"ok": True, "archive_path": "", "moved_files": [],
             "appended_sections": [], "note": "周 2026-W30 没有 daily 文件"}

    Raises:
        OSError: 仅在内部 ``unlink`` 失败的极端情况；正常路径下用 ``ok=False`` 收敛。
    """
    diary_dir = Path(diary_dir)
    if not diary_dir.is_dir():
        return {"ok": False, "error": f"diary_dir 不存在: {diary_dir}"}

    monday, sunday = _week_bounds(iso_year, iso_week)
    # 在目录里找这一周内的 daily 文件(周一到周日,含两端)
    in_week: list[tuple[dt.date, Path]] = [
        (d, entry)
        for entry in sorted(diary_dir.iterdir())
        if entry.is_file() and (d := parse_daily_filename(entry)) is not None and monday <= d <= sunday
    ]

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

    # 删除原 daily 文件(已合并到 archive);helper 抽掉重复 try/except 块。
    err = _unlink_files([p for _, p in in_week])
    if err is not None:
        return {
            "ok": False,
            "error": err,
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

    Args:
        diary_dir: diary 根目录路径。
        weeks_threshold: 阈值周数；``2`` = 保留本周 + 上周 + 上上周，
            更大值保留更多。

    Returns:
        ``dict``，schema::

            {
                "ok": True,
                "archived": [
                    {"iso_year": 2026, "iso_week": 28,
                     "archive_path": "archive/2026-W28.md",
                     "moved_files": ["2026-07-13.md", ...]},
                    ...
                ],
                "skipped": [
                    {"file": "2026-07-30.md", "reason": "in_threshold"},
                    # reason 可取值: "in_threshold" / "no_iso_week" /
                    # "parse_failed" / "stat_failed" / "unknown"
                ],
            }

        ``diary_dir`` 不存在时::

            {"ok": False, "error": "diary_dir 不存在: ..."}

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
        # stat + isocalendar 合并到一个 try,任一异常走同一档 reason。
        try:
            mtime = dt.date.fromtimestamp(entry.stat().st_mtime)
            iso_year, iso_week, _ = mtime.isocalendar()
        except OSError:
            skipped.append({"file": entry.name, "reason": "stat_failed"})
            continue

        if _within_weeks_threshold(today, _monday_of(mtime), weeks_threshold):
            skipped.append({"file": entry.name, "reason": "in_threshold"})
            continue

        key = (iso_year, iso_week)
        if key in seen_weeks:
            # 同周已归档过(可能上一轮已处理过,或文件按 ISO 周撞了)
            continue
        seen_weeks.add(key)

        r = archive_week(diary_dir, iso_year, iso_week)
        if r.get("ok"):
            archived.append(
                {
                    "iso_year": iso_year,
                    "iso_week": iso_week,
                    "archive_path": r.get("archive_path", ""),
                    "moved_files": r.get("moved_files", []),
                }
            )
        else:
            skipped.append({"file": entry.name, "reason": r.get("error", "unknown")})

    return {"ok": True, "archived": archived, "skipped": skipped}


def list_archived_weeks(diary_dir: Path) -> list[tuple[int, int]]:
    """列出 archive/ 下已归档的 (iso_year, iso_week),按 (year, week) 升序。

    Args:
        diary_dir: diary 根目录路径（内部读 ``diary_dir / "archive"``）。

    Returns:
        按 ``(year, week)`` 字典序升序的 ``(iso_year, iso_week)`` 元组列表。
        ``archive/`` 子目录不存在时返回空列表 ``[]``。
    """
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