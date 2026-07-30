"""最简压缩：超预算时丢最早的 user/assistant/tool。"""
from __future__ import annotations

from typing import Any, Protocol


class CompressionProtocol(Protocol):
    """压缩策略契约。

    实现方应：
      * ``should_compress`` 纯判等（``approx_tokens > budget``），无副作用
      * ``compress`` 触发后返回 ``messages`` 的新视图，**不**就地修改入参
    """

    def should_compress(self, messages: list[Any]) -> bool: ...
    def compress(self, messages: list[Any]) -> list[Any]: ...


_KEEP_RECENT = 6
_RESERVED_SYSTEM = 1


def approx_tokens(messages: list[Any]) -> int:
    """按 4 字符 ≈ 1 token 的粗估，累加 ``messages`` 里每条的 content 长度。

    行为细节：
      * ``getattr(m, "content", "")`` —— 缺 content 属性按空串计
      * ``or ""`` —— content 为 ``None`` 走空串分支
      * ``max(1, len // 4)`` —— 空串仍按 1 token 兜底，避免"空消息不算 token"空隙

    Args:
        messages: 待估算的消息序列；只读访问 ``.content`` 属性。

    Returns:
        int: 估算的 token 总数；空列表返回 0。
    """
    total = 0
    for m in messages:
        c = getattr(m, "content", "") or ""
        total += max(1, len(str(c)) // 4)
    return total


class SimpleCompression:
    """预算制压缩器：超出 ``budget_tokens`` 时丢最早的 user/assistant/tool。"""

    def __init__(self, budget_tokens: int = 20_000, target_ratio: float = 0.7) -> None:
        """初始化预算与目标压缩后大小。

        Args:
            budget_tokens: 触发压缩的 token 上限。
            target_ratio: 目标压缩后占 budget 的比例；目前仅缓存到
                ``self.target``，``should_compress`` 仍按 budget 判定。

        Side effects:
            写入实例属性 ``self.budget`` / ``self.target``。
        """
        self.budget = budget_tokens
        self.target = int(budget_tokens * target_ratio)

    def should_compress(self, messages: list[Any]) -> bool:
        """判断当前 ``messages`` 是否需要压缩。

        Args:
            messages: 待检查的消息序列。

        Returns:
            bool: ``approx_tokens(messages) > self.budget`` 时为 True，**边界等
                于不超**（``>`` 严格大于）。
        """
        return approx_tokens(messages) > self.budget

    def compress(self, messages: list[Any]) -> list[Any]:
        """触发压缩时：保留首条 system + 最后 _KEEP_RECENT 条非 system。

        单次扫描 ``messages``：
          * ``system`` 桶累计到 ``_RESERVED_SYSTEM`` 上限即停止 append
            （避免旧版"先全量收集再 [:1] 切片"的浪费分配）；
          * ``non_system`` 全量收集，末尾再 ``[-_KEEP_RECENT:]`` 切片。

        Args:
            messages: 待压缩的消息序列；不会被就地修改。

        Returns:
            list[Any]: 压缩后的新列表。未触发压缩时返回入参本身（同一对象）。
        """
        if not self.should_compress(messages):
            return messages
        system: list[Any] = []
        non_system: list[Any] = []
        for m in messages:
            if m.role == "system":
                # 满了就不再 append ——比"全收再切 [:1]"省一次 list 分配 + 一次切片。
                if len(system) < _RESERVED_SYSTEM:
                    system.append(m)
            else:
                non_system.append(m)
        return system + non_system[-_KEEP_RECENT:]