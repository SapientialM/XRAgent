"""世代谱：append-only JSONL。"""
from __future__ import annotations

import json
import time

from ..config.settings import get_settings


def append_generation(from_head: str, to_ref: str, reason: str, extra: dict | None = None) -> dict:
    s = get_settings()
    p = s.generations_log
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "from": from_head, "to": to_ref, "reason": reason, **(extra or {})}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_generations() -> list[dict]:
    s = get_settings()
    if not s.generations_log.exists():
        return []
    return [json.loads(line) for line in s.generations_log.read_text(encoding="utf-8").splitlines() if line.strip()]
