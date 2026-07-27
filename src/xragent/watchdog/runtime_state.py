"""运行时状态读写封装。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..config.settings import get_settings


def _path() -> Path:
    return get_settings().runtime_state_path


def read() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write(state: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def heartbeat(extra: dict[str, Any] | None = None) -> None:
    state = read()
    state["heartbeat_ts"] = time.time()
    state["pid"] = os.getpid()
    if extra:
        state.update(extra)
    write(state)


def is_alive(timeout_s: int) -> bool:
    state = read()
    ts = state.get("heartbeat_ts")
    if ts is None:
        return False
    return (time.time() - ts) <= timeout_s


def restart_count() -> int:
    return int(read().get("restart_count", 0))


def bump_restart() -> int:
    state = read()
    state["restart_count"] = int(state.get("restart_count", 0)) + 1
    write(state)
    return state["restart_count"]
