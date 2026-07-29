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
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceRecorder:
    def __init__(self, turns_dir: Path | None = None):
        s = get_settings()
        self.dir = turns_dir or s.turns_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, rec: TurnRecord) -> Path:
        path = self.dir / f"{rec.turn_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(rec.to_jsonl() + "\n")
        return path


def new_turn_id(now: float | None = None) -> str:
    """生成 turn id: YYYYMMDD-HHMMSS-mmm。

    Args:
        now: 可选 epoch 秒,用于测试时注入固定时间。
    """
    t = now if now is not None else time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + f"-{int(t * 1000) % 1000:03d}"
