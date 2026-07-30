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


def iter_jsonl(
    path: Path,
    max_lines: int | None = None,
) -> Iterator[Any]:
    """逐行读 JSONL（懒迭代）；跳过空行和解析失败行（不抛错）。

    Args:
        path: JSONL 文件路径。文件不存在时直接结束（yield 0 个），不抛 FileNotFoundError。
        max_lines: 最多 yield 多少条记录；``None`` = 读到文件末尾。
            给 ``None``/``<=0`` = 不限制（按文件实际行数）。
            用于"只取前 N 条"场景（例如最近 10 条 task 记录），不必把整文件读进内存。

    Yields:
        解析后的对象（dict / list / 标量均可，类型由调用方负责）。

    Note:
        使用 ``path.open()`` + ``for line in f`` 懒迭代，而不是
        ``read_text().splitlines()``；queue.jsonl / generations.jsonl
        长期 append 后可能很大，整文件载入内存不必要。

        encoding 用 ``utf-8-sig`` 而非 ``utf-8``：兼容外部工具（Windows 记事本、
        Excel 导出、某些 CLI ``> file.jsonl`` 重定向）写出的 BOM 文件，
        首字符 ``\\ufeff`` 会被自动剥离；纯 utf-8 文件行为完全一致。
    """
    if not path.exists():
        return
    # 循环不变式：把 "max_lines 是否生效" 提到循环外一次算好，热路径只剩一次比较。
    # 之前每行都重算 ``max_lines is not None and max_lines > 0``，N 行 = N×2 次 is/is 比较。
    has_limit = max_lines is not None and max_lines > 0
    # 懒迭代：with open() + for line in f，逐行从内核 buffer 读，
    # 避免 read_text().splitlines() 预建整文件 lines 列表的内存开销。
    # encoding="utf-8-sig" 自动处理首行 BOM（边界条件）；纯 utf-8 文件不受影响。
    with path.open("r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if has_limit and i >= max_lines:
                # 早返：避免把整文件读完才发现"我只要前 N 条"。
                # i 是已 yield 数（含被跳过的坏行/空行），但调用方关心的是
                # "最多 yield 多少个有效 rec"，用 i 偏紧一格是安全的（不会多 yield）。
                return
            line = line.strip()
            if not line:
                continue
            rec = safe_json_loads(line)
            if rec is None:
                continue
            yield rec


def read_jsonl(path: Path, max_lines: int | None = None) -> list[Any]:
    """一次性读出整个 JSONL 为 list（坏行静默跳过）。

    Args:
        path: JSONL 文件路径。
        max_lines: 透传给 ``iter_jsonl``；``None`` = 全部。

    Returns:
        解析后的对象列表；文件不存在时返回 ``[]``。
    """
    return list(iter_jsonl(path, max_lines=max_lines))


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