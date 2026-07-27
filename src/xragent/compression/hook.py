"""压缩策略 hook：Agent 可动态替换。"""
from __future__ import annotations

REGISTRY: dict[str, type] = {}


def register(name: str, cls: type) -> None:
    REGISTRY[name] = cls


def get(name: str) -> type:
    return REGISTRY[name]


from .simple import SimpleCompression  # noqa: E402

register("simple", SimpleCompression)
