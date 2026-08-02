"""最简压缩：超预算时丢最早的 user/assistant/tool。"""
from __future__ import annotations

from collections import deque
from typing import Any, Protocol


class CompressionProtocol(Protocol):
    """压缩策略契约。

    实现方应：
      * ``should_compress`` 纯判等（``approx_tokens > budget``），无副作用
      * ``compress`` 触发后返回 ``messages`` 的新视图，**不**就地修改入参
    """

    def should_compress(self, messages: list[Any]) -> bool:
        """判断 ``messages`` 是否需要压缩。

        纯判等（``approx_tokens > self.budget`` 严格大于），无副作用。
        调用方可在每次 LLM 调用前 cheap 探测一次，再决定是否调用
        :meth:`compress`。

        Args:
            messages: 待检查的消息序列；只读访问 ``.content`` 属性，
                不应被本方法就地修改。

        Returns:
            bool: 估算 token 数严格大于 ``self.budget`` 时为 ``True``；
                等于或不超过时为 ``False``。
        """
        ...

    def compress(self, messages: list[Any]) -> list[Any]:
        """把 ``messages`` 压缩到 budget 之下，返回新列表。

        实现约束：不就地修改入参；保留首条 system 消息 + 尾部
        ``_KEEP_RECENT`` 条非 system 消息；未触发压缩阈值时返回入参
        本身（同一对象，不做拷贝）。

        Args:
            messages: 待压缩的消息序列；本方法不会就地修改它。

        Returns:
            list[Any]: 压缩后的新列表；未触发压缩时直接返回入参本身。
        """
        ...


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
          * ``non_system`` 用 ``deque(maxlen=_KEEP_RECENT)`` 自动驱逐最早条目
            —— 替换原"全量收集再 ``[-_KEEP_RECENT:]`` 切片"；长消息序列下内存
            由 ``O(N)`` 降到 ``O(_KEEP_RECENT)``，且省一次尾部分片拷贝。
            ``deque.append`` 满了会从左端丢弃，``list(deque)`` 按插入顺序遍历，
            与 ``non_system[-_KEEP_RECENT:]`` 语义完全一致。

        Args:
            messages: 待压缩的消息序列；不会被就地修改。

        Returns:
            list[Any]: 压缩后的新列表。未触发压缩时返回入参本身（同一对象）。
        """
        if not self.should_compress(messages):
            return messages
        system: list[Any] = []
        non_system: deque[Any] = deque(maxlen=_KEEP_RECENT)
        for m in messages:
            if m.role == "system":
                # 满了就不再 append ——比"全收再切 [:1]"省一次 list 分配 + 一次切片。
                if len(system) < _RESERVED_SYSTEM:
                    system.append(m)
            else:
                # deque(maxlen=N) 满了自动从左端驱逐最早条目；append 是 O(1) 均摊。
                # 比 list 全量 append + 末尾 ``[-N:]`` 切片省 O(N) 内存 + 1 次拷贝。
                non_system.append(m)
        return system + list(non_system)