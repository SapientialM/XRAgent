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
        cls: 实现 :class:`CompressionProtocol` 的类对象；接受任意 ``type``，
            不强制 isinstance 检查以避免循环 import。
    """
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


# 默认注册 "simple"，Agent 启动即可使用；测试可继续 ``register("simple", X)`` 覆盖。
register("simple", SimpleCompression)