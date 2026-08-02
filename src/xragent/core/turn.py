"""Turn / TraceRecorder。"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config.settings import get_settings


@dataclass
class TurnRecord:
    turn_id: str
    ts: float
    think: str
    action: dict[str, Any] | None
    observation: dict[str, Any] | None
    score: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    wall_ms: int = 0
    error: str | None = None

    def to_jsonl(self) -> str:
        """把当前 TurnRecord 序列化为单行 JSON。

        Returns:
            ``json.dumps(asdict(self), ensure_ascii=False)`` 的结果,
            不含末尾换行（由 :meth:`TraceRecorder.write` 负责补上）。
        """
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceRecorder:
    def __init__(self, turns_dir: Path | None = None) -> None:
        """初始化 TraceRecorder,准备 turns 目录。

        Args:
            turns_dir: turns jsonl 写入目录;为 ``None`` 时回退到
                ``settings.turns_dir``。无论哪种都会 ``mkdir -p``
                确保目录存在（race-safe）。
        """
        s = get_settings()
        self.dir = turns_dir or s.turns_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, rec: TurnRecord) -> Path:
        """把一条 turn 追加写入 ``<turn_id>.jsonl``。

        文件按 ``turn_id`` 分文件,append 模式;同一 turn_id 多次
        调用会落到同一文件,方便事后 replay。

        Args:
            rec: 待写入的 turn 记录。

        Returns:
            实际写入的文件绝对路径。
        """
        path = self.dir / f"{rec.turn_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(rec.to_jsonl() + "\n")
        return path


def _format_turn_id(t: float) -> str:
    """按 ``YYYYMMDD-HHMMSS-mmm`` 格式把单次 ``time.time()`` 派生的时间戳拼成 turn id。

    把 strftime 前缀 + ms 后缀压成一处,既保证 race fix（前后两段来自同一 ``t``,
    跨秒边界不会错位）也让格式化逻辑独立于边界校验,便于单测直接调它验证格式
    稳定性,无需走 :func:`new_turn_id` 的 ``now < 0`` 校验。
    """
    prefix = time.strftime("%Y%m%d-%H%M%S", time.localtime(t))
    ms = int(t * 1000) % 1000
    return f"{prefix}-{ms:03d}"


def new_turn_id(now: float | None = None) -> str:
    """生成 turn id: ``YYYYMMDD-HHMMSS-mmm``。

    Args:
        now: 可选 epoch 秒,用于测试时注入固定时间。必须为非负数
            (epoch 自 1970-01-01 起算;负值会得到 1969 日期,无意义)。
            ``None`` 表示用 ``time.time()`` 当前值。

    Returns:
        时间格式字符串 ID,例如 ``"20260125-143022-123"``。秒以下
        部分用 ``int(t*1000) % 1000`` 取毫秒,确保同秒多次调用能区分。

    Raises:
        ValueError: ``now`` 不为 ``None`` 且 < 0（边界条件：epoch
            秒不可能为负;早 fail 比静默产生 1969 日期更安全）。
    """
    if now is not None and now < 0:
        raise ValueError(f"now must be non-negative epoch seconds, got {now}")
    t = now if now is not None else time.time()
    return _format_turn_id(t)