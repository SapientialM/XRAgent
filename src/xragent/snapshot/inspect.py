"""``xragent/turn-*`` snapshot tag 的只读 inspect 查询 —— 给人 / HITL 看。

## 为什么需要

按时间清理 (:func:`age_cleanup.cleanup_old_snapshots_by_age`) 和按数量清理
(:func:`count_cleanup.cleanup_old_snapshots_by_count`) 都是 *写* 路径;
把候选 tag 喂给 ``git tag -d`` 之前,父母 / HITL 审批人想看的不是裸
``(creatordate_unix_ts, tag_name)`` 元组,而是 *可读的元数据*:

  * ISO 年/周 (与 :mod:`util.diary_archive` 的归档文件名同套语义,跨模块对齐)
  * 距今天数 (age_in_days) —— 与 ``Settings.snapshot_retention_days`` 直接比较
  * UTC ISO 时间戳 (creatordate 已是 unix ts,转可读格式便于 review)

写一个 standalone 模块把这条 *只读* 路径补齐,让:

  * ``SideGit.cleanup_old_snapshots`` 的 ``dry_run`` 输出能被 CLI 复用
    (同一份数据,一条管道出 ``str`` 行 / ``dict`` 两条线)
  * 未来加 watchdog hook / HTTP ``/snapshots`` 端点时直接拿 ``dict``,
    不用再开第二份 ``git for-each-ref``

## 与已有模块的关系

- :mod:`._tag_index` —— 共享 *git 拉取 + 行解析* 原语;本模块直接调用
  :func:`list_xragent_turn_tags`,不重复实现 ``for-each-ref`` 调用。
- :mod:`.age_cleanup` —— *写* 路径,做 cutoff 过滤后 ``git tag -d``。
- :mod:`.count_cleanup` —— *写* 路径,做数量 slice 后 ``git tag -d``。

本模块与上面两个 *写* 路径对称:同一份 tag 列表,只读 → 增强可读性,
不引入任何 ``git`` 写操作。

## API

- :func:`list_snapshots_with_meta` —— 给一个 :class:`SideGit`,返回所有
  ``xragent/turn-*`` tag 的 ``SnapshotMeta`` 列表,**最新在前** (ts DESC)。
- :func:`format_snapshot_table` —— 把 ``SnapshotMeta`` 列表格式化成
  ``str`` (对齐列,便于直接 ``print`` / 日志),便于 HITL 审批前 dry-run
  展示。
- :func:`count_over_age` —— 给一个阈值天数,统计 *超期* tag 数 (不删,
  纯计数);与 :func:`age_cleanup.cleanup_old_snapshots_by_age` 的"会删多少"
  语义对齐 (cutoff 严格小于,与原 ``SideGit.cleanup_old_snapshots`` 一致)。

## 行为契约

- 非 git 仓库 / 无匹配 tag → 静默返回空 (与 :func:`list_xragent_turn_tags` 对齐)
- ``now`` 可注入便于测试;默认 ``time.time()``
- ISO 周用 ``dt.date.fromtimestamp(ts).isocalendar()`` (UTC),跨年周
  (如 2026-W01 含 2025-12-29~31) 自动落到正确 ISO 年。
- ``format_snapshot_table`` 走 ``str.ljust`` 不引入额外依赖。
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._tag_index import list_xragent_turn_tags

if TYPE_CHECKING:
    from .side_git import SideGit


@dataclass(frozen=True)
class SnapshotMeta:
    """单个 ``xragent/turn-*`` tag 的可读视图。

    Attributes:
        name: tag 完整名 (如 ``xragent/turn-2026-08-02T10-30-00Z``)。
        ts: creatordate 的 unix 时间戳 (来自 ``for-each-ref %(creatordate:unix)``)。
        iso_year: ISO 周所在年份 (与 :func:`util.diary_archive.list_archived_weeks`
            同套语义,跨模块对齐)。
        iso_week: ISO 周号 (1–53)。
        age_in_days: 距 ``now`` 的天数 (浮点;``(now - ts) / 86400``)。
        creatordate_iso: UTC ISO 8601 字符串 (如 ``2026-08-02T10:30:00Z``),
            便于 review 时直接读。
    """

    name: str
    ts: int
    iso_year: int
    iso_week: int
    age_in_days: float
    creatordate_iso: str

    def to_dict(self) -> dict[str, object]:
        """转 ``dict``,便于 HTTP / 日志 / JSON 序列化。

        Returns:
            ``dict`` 包含全部 6 个字段;``ts`` / ``iso_year`` / ``iso_week``
            是整数,``age_in_days`` 浮点,``creatordate_iso`` / ``name`` 字符串。
        """
        return {
            "name": self.name,
            "ts": self.ts,
            "iso_year": self.iso_year,
            "iso_week": self.iso_week,
            "age_in_days": self.age_in_days,
            "creatordate_iso": self.creatordate_iso,
        }


def _build_meta(ts: int, name: str, now: float) -> SnapshotMeta:
    """纯函数:把 ``(ts, name)`` + ``now`` 装成 ``SnapshotMeta``。

    抽到 module-level 便于单测,且 ``list_snapshots_with_meta`` 主体只
    负责"拉 + 排 + 转 dict",意图清晰。

    Args:
        ts: creatordate unix ts (整数)。
        name: tag 名 (完整 ``refs/tags/...`` 短名)。
        now: "现在" 的 unix ts (浮点);由调用方注入便于测试。

    Returns:
        填好 6 字段的 :class:`SnapshotMeta`。
    """
    d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    iso_year, iso_week, _ = d.isocalendar()
    age_in_days = (now - ts) / 86400.0
    creatordate_iso = d.strftime("%Y-%m-%dT%H:%M:%SZ")
    return SnapshotMeta(
        name=name,
        ts=ts,
        iso_year=iso_year,
        iso_week=iso_week,
        age_in_days=age_in_days,
        creatordate_iso=creatordate_iso,
    )


def list_snapshots_with_meta(
    side_git: "SideGit",
    *,
    now: float | None = None,
) -> list[SnapshotMeta]:
    """列出所有 ``xragent/turn-*`` tag,带 ISO 周 / age / 可读时间。

    与 :func:`age_cleanup.cleanup_old_snapshots_by_age` 共用
    :func:`list_xragent_turn_tags` —— 同一份 git 拉取,只读不写。

    Args:
        side_git: :class:`SideGit` 实例 (接受任意 ``SideGit``,便于测试
            注入 fake)。
        now: "现在" 的 unix ts;``None`` 走 ``time.time()``。注入便于单测
            固定 age_in_days。

    Returns:
        :class:`SnapshotMeta` 列表,**按 ts 倒序** (最新在前),便于
        review 时从最新往旧看。非 git 仓库 / 无 tag → ``[]`` (静默)。

    Note:
        与 :func:`list_xragent_turn_tags` 的 *升序* 不同 —— 本函数是给人
        看的,降序更符合直觉 (最新的 snapshot 在列表顶部)。如需升序,
        调用方 ``reversed(...)`` 即可。
    """
    if now is None:
        now = time.time()
    rows = list_xragent_turn_tags(side_git)  # 升序 (旧→新)
    # 倒序: 最新在前
    metas = [_build_meta(ts, name, now) for ts, name in reversed(rows)]
    return metas


def count_over_age(
    side_git: "SideGit",
    max_age_days: int,
    *,
    now: float | None = None,
) -> int:
    """统计 ``ts < (now - max_age_days * 86400)`` 的 tag 数 —— 纯计数, 不删。

    与 :func:`age_cleanup.cleanup_old_snapshots_by_age` 的"会删多少"
    语义对齐 (严格小于 cutoff);用于 HITL 审批前 *"如果按 30 天清,
    会清掉几个?"* 的展示。

    Args:
        side_git: :class:`SideGit` 实例。
        max_age_days: 阈值天数;``<= 0`` 走 *"全部超期"* (但调用
            :func:`age_cleanup.cleanup_old_snapshots_by_age` 时 ``<= 0``
            是禁用,这里仅做镜像计数,不动写路径)。
        now: "现在" 的 unix ts;``None`` 走 ``time.time()``。

    Returns:
        超期 tag 数 (整数, ``>= 0``)。非 git 仓库 / 无 tag → ``0``。
    """
    if now is None:
        now = time.time()
    rows = list_xragent_turn_tags(side_git)
    cutoff = int(now) - max_age_days * 86400
    return sum(1 for ts, _name in rows if ts < cutoff)


def format_snapshot_table(metas: list[SnapshotMeta]) -> str:
    """把 :class:`SnapshotMeta` 列表格式化成对齐的文本表格。

    列: ``AGE`` (右对齐 5 字符, "x.xd") / ``ISO`` (左对齐 9 字符,
    "YYYY-Www") / ``CREATED`` (左对齐 20 字符, ISO 8601) / ``NAME``。
    顶部带 ``# N snapshots`` 总数行;空列表返回 ``"# 0 snapshots\\n"``。

    Args:
        metas: :class:`SnapshotMeta` 列表;**按调用方给的顺序**输出
            (本函数不二次排序)。

    Returns:
        多行 ``str``;末尾保留 ``\\n``,便于 ``print(...)`` / 写文件。
    """
    out_lines: list[str] = [f"# {len(metas)} snapshots"]
    if not metas:
        return "\n".join(out_lines) + "\n"
    out_lines.append(
        f"{'AGE':>5}  {'ISO':<9}  {'CREATED':<20}  NAME"
    )
    for m in metas:
        out_lines.append(
            f"{m.age_in_days:>5.1f}d  "
            f"{m.iso_year}-W{m.iso_week:02d}  "
            f"{m.creatordate_iso:<20}  {m.name}"
        )
    return "\n".join(out_lines) + "\n"


__all__ = [
    "SnapshotMeta",
    "count_over_age",
    "format_snapshot_table",
    "list_snapshots_with_meta",
]