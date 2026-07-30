"""memory 工具。"""
from __future__ import annotations

from typing import Any

from ..memory.manager import MemoryManager


def memory_save(category: str, content: str) -> dict[str, Any]:
    """保存一条 fact 到长期记忆（SQLite）。

    Args:
        category: fact 分类标签（用于按类过滤 / top-N 频次统计）。
        content: fact 正文。允许中文 / emoji / 多行文本。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终为 True（底层异常不在工具层兜底）
            * ``id`` (int): 新 fact 的数据库主键，供后续 update / delete 引用
    """
    m = MemoryManager()
    # 5.1: save_fact 返回 Fact 而非 int, 这里取 .id 兼容原 LLM-facing 接口。
    fact = m.save_fact(category=category, content=content, source_turn="agent")
    return {"ok": True, "id": fact.id}


def memory_recall_range(
    start_ts: float | None = None,
    end_ts: float | None = None,
    category: str | None = None,
    k: int = 1000,
) -> dict[str, Any]:
    """按时间窗口从长期记忆召回 fact（newest first）。

    与 ``memory_recall`` (关键词 LIKE) 互补 —— 本工具回答"什么时候说的"。
    ``start_ts`` / ``end_ts`` 任一为 ``None`` 都表示对应端开放。

    Args:
        start_ts: 下界时间戳（Unix seconds）；``None`` 表示 -∞。
        end_ts: 上界时间戳；``None`` 表示 +∞。
        category: 按分类过滤；``None`` 表示所有分类。
        k: 最多返回条数（按 ts 降序截断），默认 1000。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 ``id`` (int) / ``ts`` (float)
              / ``category`` (str) / ``content`` (str) 四个键
    """
    m = MemoryManager()
    facts = m.recall_range(start_ts=start_ts, end_ts=end_ts, category=category, k=k)
    return {
        "ok": True,
        "count": len(facts),
        "facts": [
            {
                "id": f.id,
                "ts": f.ts,
                "category": f.category,
                "content": f.content,
            }
            for f in facts
        ],
    }


def memory_top_frequent(
    n: int = 10,
    category: str | None = None,
    min_count: int = 2,
) -> dict[str, Any]:
    """按 content 频次降序返回 top-N（用于回答"用户反复说过的点是什么"）。

    Args:
        n: 最多返回条数，默认 10。
        category: 按分类过滤；``None`` 表示跨所有分类聚合。
        min_count: 最低出现次数（默认 2，过滤一次性噪音）；
            需要召回全部时显式传 ``min_count=1``。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回条目数
            * ``top`` (list[dict[str, int]]): 每条含 ``content`` (str) + ``count`` (int)
    """
    m = MemoryManager()
    top = m.top_frequent(n=n, category=category, min_count=min_count)
    return {
        "ok": True,
        "count": len(top),
        "top": [{"content": c, "count": cnt} for c, cnt in top],
    }
