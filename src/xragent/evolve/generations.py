"""世代谱：append-only JSONL。

每次金蝉脱壳（``metamorphose``）成功后追加一行；旧世代的历史由此可追溯。
之前这里的 ``list_generations`` 手写 4 行：read_text → splitlines → if line.strip() → json.loads，
并且坏行（JSON 截断 / 半行）会直接抛 JSONDecodeError 让上层崩。现抽到
``util.jsonl_utils``：``append_generation`` 用 ``append_jsonl``（自动 mkdir parent），
``list_generations`` 用 ``read_jsonl``（坏行静默跳过 + 文件缺失返回 ``[]``）。
"""
from __future__ import annotations

import time

from ..config.settings import get_settings
from ..util.jsonl_utils import append_jsonl, read_jsonl


def append_generation(from_head: str, to_ref: str, reason: str, extra: dict | None = None) -> dict:
    """追加一条世代记录到 ``evolve/generations.jsonl``。

    Args:
        from_head: 旧世代的 HEAD commit。
        to_ref: 新世代的 ref（branch/tag/commit）。
        reason: 为什么要蜕皮（人类可读短句）。
        extra: 其它要存的字段（如 ``compile_ok``）。

    Returns:
        写入的 record（包含自动加上的 ``ts``）。
    """
    s = get_settings()
    rec = {"ts": time.time(), "from": from_head, "to": to_ref, "reason": reason, **(extra or {})}
    append_jsonl(s.generations_log, rec)
    return rec


def list_generations() -> list[dict]:
    """读出全部世代记录。

    Returns:
        全部 record list；文件不存在返回 ``[]``；坏行被静默跳过。
    """
    s = get_settings()
    return read_jsonl(s.generations_log)