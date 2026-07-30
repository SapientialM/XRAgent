"""世代谱：append-only JSONL。

每次金蝉脱壳（``metamorphose``）成功后追加一行；旧世代的历史由此可追溯。
之前这里的 ``list_generations`` 手写 4 行：read_text → splitlines → if line.strip() → json.loads，
并且坏行（JSON 截断 / 半行）会直接抛 JSONDecodeError 让上层崩。现抽到
``util.jsonl_utils``：``append_generation`` 用 ``append_jsonl``（自动 mkdir parent），
``list_generations`` 用 ``read_jsonl``（坏行静默跳过 + 文件缺失返回 ``[]``）。

**typing pass (v0.x)**：把 ``append_generation`` 的 ``extra`` 参数从 ``dict | None``
改成 ``dict[str, Any] | None``；两个函数的返回类型 ``dict`` / ``list[dict]``
都改成 ``dict[str, Any]`` / ``list[dict[str, Any]]``，跟 ``util.jsonl_utils``
的 schema 对齐。
"""
from __future__ import annotations

import time
from typing import Any

from ..config.settings import get_settings
from ..util.jsonl_utils import append_jsonl, read_jsonl


def append_generation(
    from_head: str,
    to_ref: str,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一条世代记录到 ``evolve/generations.jsonl``。

    Args:
        from_head: 旧世代的 HEAD commit（40 字符 hex）。
        to_ref: 新世代的 ref（branch/tag/commit）；供后续 metamorphose 链路追溯。
        reason: 为什么要蜕皮（人类可读短句，写入 JSONL 的 ``reason`` 字段）。
        extra: 其它要存的字段（如 ``compile_ok`` / ``tests_passed`` /
            ``diff_files`` 等）；为 ``None`` 时不附加额外字段。

    Returns:
        dict[str, Any]: 实际写入的 record，包含自动加上的 ``ts``
        （``time.time()`` 的 float epoch）。调用方通常无需关心返回值，
        但 ``append_jsonl`` 成功后回吐一份方便测试断言 / 链式调用。
    """
    s = get_settings()
    rec: dict[str, Any] = {
        "ts": time.time(),
        "from": from_head,
        "to": to_ref,
        "reason": reason,
        **(extra or {}),
    }
    append_jsonl(s.generations_log, rec)
    return rec


def list_generations() -> list[dict[str, Any]]:
    """读出全部世代记录。

    Returns:
        list[dict[str, Any]]: 全部 record 列表（按 JSONL 写入顺序）；文件
        不存在返回 ``[]``；坏行（JSON 截断 / 半行）由 :func:`read_jsonl`
        静默跳过，不抛 :class:`json.JSONDecodeError`。
    """
    s = get_settings()
    return read_jsonl(s.generations_log)