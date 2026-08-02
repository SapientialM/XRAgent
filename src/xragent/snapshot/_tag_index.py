"""``xragent/turn-*`` snapshot tag 的共享索引原语。

## 为什么需要

两个清理路径（按时间 :meth:`SideGit.cleanup_old_snapshots`、按数量
:func:`count_cleanup.cleanup_old_snapshots_by_count`）原本各写一份
``git for-each-ref`` 调用 + ``refname:short\tcreatordate:unix`` 行解析 +
``git tag -d`` 逐条删除循环。三段逻辑彼此等价，重复 3×，任一处格式微调
（比如 ``%09`` 改 ``\t``）就得三处同步改。本模块抽出这三个原语，让两个
清理路径只剩各自独有的策略（cutoff 过滤 vs 数量 slice）。

## 公开 API

- :func:`list_xragent_turn_tags` —— 跑 ``git for-each-ref`` 拉所有
  ``xragent/turn-*`` tag，按 creatordate 升序解析为 ``(ts, name)`` 列表。
- :func:`parse_xragent_turn_tags` —— 纯函数版行解析，便于无 git 单测。
- :func:`delete_tags` —— 逐条 ``git tag -d``，单条失败不阻塞整体。

## 设计约束

- ``is_repo()`` / ``for-each-ref`` / ``git tag -d`` 任一失败一律静默
  返回空结果／被跳过的 tag —— 与两个原清理函数一致，避免 watchdog 调用
  炸流程。
- 行解析对 ``%09`` 分隔 + 整数 ``ts`` 双重容错：分隔缺失或非整数 ts 都
  静默跳过，与原 ``cleanup_old_snapshots`` 行为一致。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .side_git import SideGit


def list_xragent_turn_tags(side_git: "SideGit") -> list[tuple[int, str]]:
    """拉取所有 ``xragent/turn-*`` tag，按 creatordate **升序**（旧→新）返回。

    与原 :meth:`SideGit.cleanup_old_snapshots` 中 ``for-each-ref`` + 行解析
    段等价：先 ``is_repo()`` 守卫，再 ``for-each-ref refs/tags/xragent/turn-*``
    取 ``refname:short\tcreatordate:unix``，逐行解析为 ``(ts, name)``。

    Args:
        side_git: :class:`SideGit` 实例（接受任意 ``SideGit``）。

    Returns:
        ``(creatordate_unix_ts, tag_name)`` 元组列表，按 ts 升序。
        非 git 仓库 / 无匹配 tag → ``[]``（静默，不抛）。

    Note:
        函数名复数 + 升序约定与原 ``cleanup_old_snapshots`` 中
        ``candidates.sort()`` 对齐；调用方若需要倒序，调用 ``sorted(..., reverse=True)``
        即可（如 ``cleanup_old_snapshots_by_count``）。
    """
    if not side_git.is_repo():
        return []
    # for-each-ref 在无匹配 ref 时 exit 1 → git_run 抛 RuntimeError，
    # 这里静默吞下，当作"无 tag"。
    try:
        out = side_git._run(  # noqa: SLF001 — 复用 SideGit._run，与原 cleanup_old_snapshots 同语义
            "for-each-ref",
            "refs/tags/xragent/turn-*",
            "--format=%(refname:short)%09%(creatordate:unix)",
        )
    except RuntimeError:
        return []
    return parse_xragent_turn_tags(out)


def parse_xragent_turn_tags(out: str) -> list[tuple[int, str]]:
    """纯函数版行解析。

    把 ``git for-each-ref --format='%(refname:short)%09%(creatordate:unix)'``
    的输出解析为 ``(creatordate_unix_ts, tag_name)`` 元组列表，按 ts 升序。
    无 git 也能单测。

    解析容错:
      - ``\\t`` 分隔缺失 → 跳过该行（不抛）
      - ``ts`` 非整数 → 跳过该行（不抛）
      - 空字符串 → 返回 ``[]``
    """
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
    rows.sort()  # ASC: 旧 → 新，与原 cleanup_old_snapshots 对齐
    return rows


def delete_tags(side_git: "SideGit", names: list[str]) -> list[str]:
    """逐条 ``git tag -d``，单条失败不阻塞整体。

    与原 :meth:`SideGit.cleanup_old_snapshots` 末尾删除循环等价：
    遍历 ``names``，逐条执行 ``git tag -d``，失败（RuntimeError）则
    跳过该条继续处理下一条，最终返回成功删除的 tag 名（按输入顺序）。

    Args:
        side_git: :class:`SideGit` 实例。
        names: 待删除 tag 名列表。

    Returns:
        成功删除的 tag 名列表（输入顺序的子集）。
    """
    removed: list[str] = []
    for name in names:
        try:
            side_git._run("tag", "-d", name)  # noqa: SLF001
            removed.append(name)
        except RuntimeError:
            # 单 tag 删失败不阻塞其他 tag —— 与 cleanup_old_snapshots 对齐
            pass
    return removed


__all__ = [
    "delete_tags",
    "list_xragent_turn_tags",
    "parse_xragent_turn_tags",
]