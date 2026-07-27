"""最简压缩：超预算时丢最早的 user/assistant/tool。"""
from __future__ import annotations

from typing import Protocol


class CompressionProtocol(Protocol):
    def should_compress(self, messages: list) -> bool: ...
    def compress(self, messages: list) -> list: ...


_KEEP_RECENT = 6
_RESERVED_SYSTEM = 1


def approx_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        c = getattr(m, "content", "") or ""
        total += max(1, len(str(c)) // 4)
    return total


class SimpleCompression:
    def __init__(self, budget_tokens: int = 20_000, target_ratio: float = 0.7):
        self.budget = budget_tokens
        self.target = int(budget_tokens * target_ratio)

    def should_compress(self, messages: list) -> bool:
        return approx_tokens(messages) > self.budget

    def compress(self, messages: list) -> list:
        if not self.should_compress(messages):
            return messages
        system = [m for m in messages if m.role == "system"][:_RESERVED_SYSTEM]
        non_system = [m for m in messages if m.role != "system"]
        tail = non_system[-_KEEP_RECENT:]
        return system + tail
