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
        """触发压缩时：保留首条 system + 最后 _KEEP_RECENT 条非 system。

        单次扫描 ``messages``：
          * ``system`` 桶累计到 ``_RESERVED_SYSTEM`` 上限即停止 append
            （避免旧版"先全量收集再 [:1] 切片"的浪费分配）；
          * ``non_system`` 全量收集，末尾再 ``[-_KEEP_RECENT:]`` 切片。
        """
        if not self.should_compress(messages):
            return messages
        system: list = []
        non_system: list = []
        for m in messages:
            if m.role == "system":
                # 满了就不再 append ——比"全收再切 [:1]"省一次 list 分配 + 一次切片。
                if len(system) < _RESERVED_SYSTEM:
                    system.append(m)
            else:
                non_system.append(m)
        return system + non_system[-_KEEP_RECENT:]