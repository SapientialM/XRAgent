"""压缩策略 hook：Agent 可动态替换。"""
from __future__ import annotations

from typing import Any

from .simple import SimpleCompression

REGISTRY: dict[str, type[Any]] = {}


def register(name: str, cls: type[Any]) -> None:
    """注册一个压缩策略类到 :data:`REGISTRY`。

    调用方应保证 ``cls`` 实现 :class:`~xragent.compression.simple.CompressionProtocol`
    （即同时提供 ``should_compress`` 与 ``compress``）。本函数不做协议校验，
    留到第一次 ``get`` 出来的实例调用方法时才暴露错误——保留轻量注册的契约。

    Args:
        name: 策略名（Agent 配置 / ``Settings`` 里会引用）。同名重复注册直接覆盖。
            必须是去除前后空白后非空的字符串；空串 / ``None`` / 纯空白会被拒绝
            并抛 ``ValueError``，避免把空 key 静默写入 :data:`REGISTRY` 后
            下次 :func:`get` 时才 ``KeyError``，让调用方难以追溯根因。
        cls: 实现 :class:`CompressionProtocol` 的类对象；必须可调用
            （callable），不允许 ``None`` / 实例对象 / 普通函数当策略类用。
            不做 ``isinstance(cls, type)`` 检查以避免循环 import，但
            ``callable(cls)`` 能拦住最常见的传错场景。

    Raises:
        ValueError: ``name`` 不是非空字符串，或 ``cls`` 不可调用。
    """
    if not isinstance(name, str) or not name.strip():
        # 边界：原版对 None / "" / "   " 都默默写入 REGISTRY，后续 get 出来
        # KeyError / AttributeError 时调用方很难定位是这里写了坏 key。
        raise ValueError(f"hook.register: name must be a non-empty str, got {name!r}")
    if not callable(cls):
        # 边界：传实例 (e.g. SimpleCompression(...)) 或 None / 普通函数，
        # 都会让后续 get(...)() 调用时崩。提前拦下。
        raise ValueError(f"hook.register: cls must be callable, got {cls!r}")
    REGISTRY[name] = cls


def get(name: str) -> type[Any]:
    """按名字取出已注册的压缩策略类。

    Args:
        name: 之前 :func:`register` 注册过的策略名。

    Returns:
        type[Any]: 对应的类对象（不是实例——调用方需自行 ``cls(...)``）。

    Raises:
        KeyError: ``name`` 不在 :data:`REGISTRY` 里；由 ``dict.__getitem__`` 直接抛。
    """
    return REGISTRY[name]


def list_registered() -> list[str]:
    """返回当前已注册策略名列表（按插入顺序）。

    主要给调试 / 日志 / 配置 UI 列举用——v0.3 路线图要求"摘要压缩 hook
    启用 Agent 可写自己的压缩策略"，至少要能枚举当前 :data:`REGISTRY`
    里有什么可选。对调用方完全只读：返回新 ``list``，不会随后续
    ``register`` 而变化（快照语义）。

    Returns:
        list[str]: 当前 :data:`REGISTRY` 的全部 key 副本。
    """
    # 返回新 list 而不是 REGISTRY.keys() 视图：避免调用方无意中持有视图、
    # 在后续 register 后看到"幽灵变化"。
    return list(REGISTRY.keys())


register("simple", SimpleCompression)
