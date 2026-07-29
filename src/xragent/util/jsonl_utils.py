"""JSONL（JSON Lines）读写工具。

把"read_text → splitlines → strip → safe_json_loads → 过滤 None"模式从两处抽出来：
  - ``autonomous._recent_titles`` 读 ``memory/queue.jsonl``（5+ 行 for-loop + if）
  - ``evolve.generations.list_generations`` 读 ``evolve/generations.jsonl``
    （1 行 list comp，但 broken line 会让整个 list comp 抛 JSONDecodeError）

两处都同构：append-only JSONL → 读出 list[dict] / iter dict → 跳过空行/坏行。
抽到 util 后调用方只需 ``for rec in iter_jsonl(p): ...``，错误行不再让上层崩。

注意：``iter_jsonl``/``read_jsonl`` 默认**静默跳过**坏行（不抛错），因为这些是
append-only 日志；坏行只影响这一行，不该让整次读失败。调用方如果需要"严格
模式"，可改用 ``json.loads(line)`` + 自己 try/except。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .json_utils import safe_json_loads


def iter_jsonl(path: Path) -> Iterator[Any]:
    """逐行读 JSONL；跳过空行和解析失败行（不抛错）。

    Args:
        path: JSONL 文件路径。文件不存在时直接结束（yield 0 个），不抛 FileNotFoundError。

    Yields:
        解析后的对象（dict / list / 标量均可，类型由调用方负责）。
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = safe_json_loads(line)
        if rec is None:
            continue
        yield rec


def read_jsonl(path: Path) -> list[Any]:
    """一次性读出整个 JSONL 为 list（坏行静默跳过）。

    Args:
        path: JSONL 文件路径。

    Returns:
        解析后的对象列表；文件不存在时返回 ``[]``。
    """
    return list(iter_jsonl(path))


def append_jsonl(path: Path, rec: Any) -> None:
    """追加一条 JSON record 到 JSONL 文件（自动 mkdir parent）。

    行为细节：
      * ``ensure_ascii=False``：保留中文字符；日志可读性 > 文件体积
      * 末尾强制 ``\\n``：append-only 格式要求
      * 失败抛原始异常（不吞）；由调用方决定是否 fallback

    Args:
        path: 目标 JSONL 路径；父目录会自动 ``mkdir(parents=True, exist_ok=True)``。
        rec: 任意可被 ``json.dumps`` 序列化的对象。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
