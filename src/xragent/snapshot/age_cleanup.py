"""按时间清理 snapshot tag —— :meth:`SideGit.cleanup_old_snapshots` 的 standalone 镜像。

## 为什么需要

:class:`SideGit.cleanup_old_snapshots` 早已能按 creatordate 删除 ``xragent/turn-*``
tag，但它把 ``git for-each-ref`` + 行解析 + 逐条 ``git tag -d`` 三段逻辑**内联**
在方法体里。同期的 v0.5.8 refactor 把数量清理
(:func:`count_cleanup.cleanup_old_snapshots_by_count`) 抽到了独立模块并走
:mod:`._tag_index` 的共享 helper（``list_xragent_turn_tags`` / ``delete_tags``）
—— ``count_cleanup.py`` 是干净的 module-level API，而时间清理没有平行的
standalone 模块，**结构和数量清理不对称**。

本模块提供 :func:`cleanup_old_snapshots_by_age`，把同样的 refactor 应用到时间
路径：模块级函数 + 全走 ``_tag_index`` helper，让两个清理路径都只剩各自的策略
（cutoff 过滤 vs 数量 slice），便于单测、独立调用、未来加 scheduler / cron hook。

## API

- :func:`cleanup_old_snapshots_by_age` —— 单次调用，按 creatordate cutoff
  删除 ``xragent/turn-*`` tag，返回被删除（或候选删除）的 tag 名列表。

## 行为契约

- ``max_age_days <= 0`` → 禁用，直接返回 ``[]``
- 非 git 仓库 / ``git for-each-ref`` 失败 → 静默返回 ``[]``
- 仅匹配 ``xragent/turn-*`` 前缀，用户手工 ``v0.1`` / ``baseline`` 不动
- ``dry_run=True`` 时仅列候选，不实际 ``git tag -d``
- 单 tag 删除失败不阻塞其他 tag（与 ``cleanup_old_snapshots_by_count`` 对齐）
- 返回列表按 **creatordate 旧→新** 排序，与 :meth:`SideGit.cleanup_old_snapshots`
  行为对齐
- cutoff = ``int(time.time()) - max_age_days * 86400``，含边界严格小于（``ts < cutoff``）

**v0.5.8 refactor (本轮)**: 把原本 inline 的 ``git for-each-ref`` 调用 + 行解析 +
逐条 ``git tag -d`` 循环全部走 :mod:`._tag_index` 的 helper。 ``count_cleanup.py``
已经在上一轮做了同样事 —— 现在 ``SideGit.cleanup_old_snapshots`` 仍然是 inline
版本（v0.5.9+ 可考虑让方法本身 delegate 到本函数，但本轮先加 standalone API，
不强行改方法体）。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ._tag_index import delete_tags, list_xragent_turn_tags

if TYPE_CHECKING:
    from .side_git import SideGit


def cleanup_old_snapshots_by_age(
    side_git: "SideGit",
    max_age_days: int,
    dry_run: bool = False,
) -> list[str]:
    """按 creatordate 清理 ``xragent/turn-*`` tag —— standalone 模块级 API。

    镜像 :meth:`SideGit.cleanup_old_snapshots` 的策略 + :func:`count_cleanup.cleanup_old_snapshots_by_count`
    的"走 ``_tag_index`` helper" 写法，便于独立单测、独立调度（cron /
    watchdog hook）。策略本身简单：算出 cutoff = ``now - max_age_days * 86400``，
    保留 ``ts >= cutoff`` 的 tag，删 ``ts < cutoff`` 的（严格小于，与
    :meth:`SideGit.cleanup_old_snapshots` 对齐）。

    Args:
        side_git: :class:`SideGit` 实例（接受任意 ``SideGit``，便于测试
            注入 fake）。
        max_age_days: 保留天数上限；``<= 0`` 禁用，直接返回 ``[]``。
            ``None`` 走 :attr:`Settings.snapshot_retention_days`（默认 30），
            与 :meth:`SideGit.cleanup_old_snapshots` 对齐。
        dry_run: True 仅列候选 tag，不实际 ``git tag -d``。

    Returns:
        被删除（``dry_run=False``）或候选删除（``dry_run=True``）的 tag
        名列表，按 creatordate 旧→新排序（与 :meth:`SideGit.cleanup_old_snapshots`
        一致）。

    Side effects:
        ``dry_run=False`` 时对每个候选 tag 执行 ``git tag -d``；单条失败
        不阻塞其他 tag。

    Note:
        严格小于 cutoff（``ts < cutoff``）—— 31 天前的 tag 在
        ``max_age_days=30`` 时会被删，与原 ``cleanup_old_snapshots`` 语义
        一致；想"保留 N 天内"用 ``max_age_days=N``，想"超过 N 天就清"
        同样传 N。
    """
    # max_age_days 禁用路径：None → settings.snapshot_retention_days，与
    # SideGit.cleanup_old_snapshots 早返语义对齐；<= 0 → 禁用
    if max_age_days is None:
        from ..config.settings import get_settings  # 延迟 import 避免循环

        max_age_days = get_settings().snapshot_retention_days
    if max_age_days <= 0:
        return []
    # 非 repo 守卫 / for-each-ref 失败 → 静默 [] 由 list_xragent_turn_tags 内部处理
    rows = list_xragent_turn_tags(side_git)  # 升序：旧 → 新
    cutoff = int(time.time()) - max_age_days * 86400
    # 升序 rows + 严格小于 cutoff → 切片找出最旧且超期的若干
    targets = [name for ts, name in rows if ts < cutoff]
    # 已是旧→新顺序，无需再 sort
    if dry_run or not targets:
        return targets

    # 走 _tag_index.delete_tags：单条失败不阻塞整体，与 cleanup_old_snapshots 对齐
    return delete_tags(side_git, targets)


__all__ = ["cleanup_old_snapshots_by_age"]