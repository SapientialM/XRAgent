"""按数量上限清理 snapshot tag —— ``cleanup_old_snapshots`` 的"数量兜底"。

## 为什么需要

:class:`SideGit.cleanup_old_snapshots` 只按 **时间** 维度清理：保留最近
N 天的 ``xragent/turn-*`` tag。但当 Agent 在短窗口内高频 snapshot
（自检 / 迭代 / auto-fix 循环），单个 ISO 周就能堆出几十上百个 tag，而
它们都不超过默认 30 天保留期 → 时间维度永远不触发清理 → ``git tag -l``
/ ``git push --tags`` 越来越慢，``refs/tags/`` 命名空间持续膨胀。

本模块提供 ``cleanup_old_snapshots_by_count(max_count)``：**按数量** 兜底，
保留 creatordate 最新的 N 个 ``xragent/turn-*`` tag，删其余的。与时间
清理互不冲突（时间清理管"老的"，数量清理管"多的"），组合使用保证
``xragent/turn-*`` tag 集合永远有上界。

## API

- :func:`cleanup_old_snapshots_by_count` —— 单次调用，删除超过 ``max_count``
  阈值的 tag，返回被删除（或候选删除）的 tag 名列表。

## 行为契约

- ``max_count <= 0`` → 禁用，直接返回 ``[]``
- 非 git 仓库 / ``git for-each-ref`` 失败 → 静默返回 ``[]``
- 仅匹配 ``xragent/turn-*`` 前缀，用户手工 ``v0.1`` / ``baseline`` 不动
- ``dry_run=True`` 时仅列候选，不实际 ``git tag -d``
- 单 tag 删除失败不阻塞其他 tag（与 ``cleanup_old_snapshots`` 对齐）
- 返回列表按 **creatordate 旧→新** 排序，与 ``cleanup_old_snapshots`` 一致
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .side_git import SideGit


def cleanup_old_snapshots_by_count(
    side_git: "SideGit",
    max_count: int,
    dry_run: bool = False,
) -> list[str]:
    """保留 ``xragent/turn-*`` tag 中 creatordate 最新的 ``max_count`` 个。

    按 creatordate 倒序排列所有 ``xragent/turn-*`` tag，丢弃第 ``max_count``
    个之后（即最旧）的那些。返回被删除（或 ``dry_run=True`` 时候选删除）的
    tag 名列表，**按 creatordate 旧→新排序**，与
    :meth:`SideGit.cleanup_old_snapshots` 行为对齐。

    Args:
        side_git: :class:`SideGit` 实例（接受任意 ``SideGit``，便于测试
            注入 fake）。
        max_count: 保留上限；``<= 0`` 禁用，直接返回 ``[]``。
        dry_run: True 仅列候选 tag，不实际删除。

    Returns:
        被删除（``dry_run=False``）或候选删除（``dry_run=True``）的 tag
        名列表，按 creatordate 旧→新排序。

    Side effects:
        ``dry_run=False`` 时对每个候选 tag 执行 ``git tag -d``；单条失败
        不阻塞其他 tag。
    """
    # 早返：禁用 / 非 repo —— 与 cleanup_old_snapshots 早返语义对齐
    if max_count <= 0:
        return []
    if not side_git.is_repo():
        return []

    # 一次性取 creatordate:unix + refname。SideGit._run 失败（无匹配 ref）
    # 仍会抛 RuntimeError（git exit 1），这里静默吞下 → 当作"无 tag"。
    try:
        out = side_git._run(  # noqa: SLF001 — 复用 SideGit._run，与 cleanup_old_snapshots 同语义
            "for-each-ref",
            "refs/tags/xragent/turn-*",
            "--format=%(refname:short)%09%(creatordate:unix)",
        )
    except RuntimeError:
        return []

    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        name, ts_str = line.split("\t", 1)
        try:
            ts = int(ts_str)
        except ValueError:
            continue
        rows.append((ts, name))

    # 倒序：新→旧。
    # - rows[:max_count] = 保留段（最新 N 个）
    # - rows[max_count:] = 删除段（新→旧方向的最后 N 段，即旧→新方向
    #   的前 N 段）→ 取 reversed 得"旧→新"顺序返回
    rows.sort(reverse=True)
    targets = [name for _, name in rows[max_count:]]
    targets.reverse()  # 新→旧 → 旧→新（与 cleanup_old_snapshots 返回顺序对齐）

    if dry_run or not targets:
        return targets

    removed: list[str] = []
    for name in targets:
        try:
            side_git._run("tag", "-d", name)  # noqa: SLF001
            removed.append(name)
        except RuntimeError:
            # 单 tag 删失败不阻塞其他 tag —— 与 cleanup_old_snapshots 对齐
            pass
    return removed


__all__ = ["cleanup_old_snapshots_by_count"]