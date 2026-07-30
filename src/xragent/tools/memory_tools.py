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


def memory_recall(
    query: str = "",
    k: int = 5,
    category: str | None = None,
) -> dict[str, Any]:
    """关键词 LIKE 召回 fact（newest first），回答"我说过什么关于 X 的事"。

    与 ``memory_recall_range`` (时间窗口) 互补 —— 本工具回答"说过什么"。

    Args:
        query: 关键词，匹配 ``facts.content LIKE '%query%'``。空字符串表示
            退化为全量最新 k 条（等价于不传 WHERE 子句）。
        k: 最多返回条数，默认 5（关键词召回通常用于"补上下文"，不宜一次塞太多）。
        category: 按分类过滤；``None`` 表示跨类搜索。

    Returns:
        ``dict[str, Any]``，LLM 工具契约字段：
            * ``ok`` (bool): 始终 True
            * ``count`` (int): 实际返回的 fact 数
            * ``facts`` (list[dict[str, Any]]): 每条含 ``id`` (int) / ``ts`` (float)
              / ``category`` (str) / ``content`` (str) 四个键

    索引:
        走 ``idx_facts_category_ts`` (category 非空时) 或 ``idx_facts_ts`` (无 category
        时)，均能让 ``ORDER BY ts DESC LIMIT ?`` 提前结束。
    """
    m = MemoryManager()
    # k 兜底: LLM 可能传 0 / 负数; clip 到 [1, 1000] 防止空结果或一次拉爆。
    k_eff = max(1, min(int(k), 1000))
    facts = m.recall(query=query, k=k_eff, category=category)
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
