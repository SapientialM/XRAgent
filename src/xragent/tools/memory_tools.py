"""memory 工具。"""
from __future__ import annotations

from ..memory.manager import MemoryManager


def memory_save(category: str, content: str) -> dict:
    m = MemoryManager()
    # 5.1: save_fact 返回 Fact 而非 int, 这里取 .id 兼容原 LLM-facing 接口。
    fact = m.save_fact(category=category, content=content, source_turn="agent")
    return {"ok": True, "id": fact.id}


def memory_recall_range(
    start_ts: float | None = None,
    end_ts: float | None = None,
    category: str | None = None,
    k: int = 1000,
) -> dict:
    """按时间窗口从长期记忆召回 fact (newest first)。

    与 memory_recall (关键词 LIKE) 互补 —— 本工具回答"什么时候说的"。
    start_ts/end_ts 为 None 时分别表示 -∞ / +∞。
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
) -> dict:
    """按 content 频次降序返回 top-N。

    用于回答"用户反复说过的点是什么"。min_count=2 (默认) 过滤一次性噪音;
    需要召回全部时显式传 min_count=1。
    """
    m = MemoryManager()
    top = m.top_frequent(n=n, category=category, min_count=min_count)
    return {
        "ok": True,
        "count": len(top),
        "top": [{"content": c, "count": cnt} for c, cnt in top],
    }