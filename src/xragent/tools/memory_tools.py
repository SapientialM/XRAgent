"""memory 工具。"""
from __future__ import annotations

from ..memory.manager import MemoryManager


def memory_save(category: str, content: str) -> dict:
    m = MemoryManager()
    # 5.1: save_fact 返回 Fact 而非 int, 这里取 .id 兼容原 LLM-facing 接口。
    fact = m.save_fact(category=category, content=content, source_turn="agent")
    return {"ok": True, "id": fact.id}