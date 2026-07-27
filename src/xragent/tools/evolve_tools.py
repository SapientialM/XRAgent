"""蜕皮 + terminate 工具。"""
from __future__ import annotations

import json
import os
import signal

from ..evolve.metamorphosis import metamorphose
from ..config.settings import get_settings


def propose_self_replace(reason: str, entry: str = "src/xragent/main.py") -> dict:
    s = get_settings()
    if not s.evolution_enabled:
        return {"ok": False, "blocked_by": "evolution_disabled"}
    return metamorphose(reason=reason, entry=entry)


def terminate(reason: str) -> dict:
    s = get_settings()
    from ..memory.manager import MemoryManager
    m = MemoryManager()
    m.save_fact(category="lifecycle", content=f"terminate: {reason}", source_turn="agent")
    runtime = s.repo_root / "runtime_state.json"
    state = {}
    if runtime.exists():
        try:
            state = json.loads(runtime.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state["restart_suppressed"] = True
    state["terminate_reason"] = reason
    runtime.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"ok": True, "reason": reason}
