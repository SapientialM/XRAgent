"""memory 工具。"""
from __future__ import annotations

from ..memory.manager import MemoryManager


def memory_save(category: str, content: str) -> dict:
    m = MemoryManager()
    fid = m.save_fact(category=category, content=content, source_turn="agent")
    return {"ok": True, "id": fid}
