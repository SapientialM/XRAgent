"""蜕皮 + terminate 工具。"""
from __future__ import annotations

import json
import os
import signal

from ..evolve.metamorphosis import metamorphose
from ..config.settings import get_settings


def propose_self_replace(reason: str, entry: str = "src/xragent/main.py") -> dict:
    """触发「金蝉脱壳」自蜕皮流程（commit → push → 编译 → supervisor 切换）。

    这是 DREAM 第三节说的"质变时才蜕皮"工具入口。调用前应已通过 side-git
    快照做过可回滚的准备；流程本身由 :func:`metamorphose` 完成，工具层
    只负责 Settings 闸门与结果转发。

    Args:
        reason: 蜕皮动机；会被写入 ``evolve/generations.jsonl`` 的
            ``reason`` 字段，供后续世代回溯用。建议一句话讲清"为什么要换"。
        entry: 新一代入口模块路径，默认 ``src/xragent/main.py``。

    Returns:
        闸门关闭时 ``{"ok": False, "blocked_by": "evolution_disabled"}``；
        其余情况透传 :func:`metamorphose` 的返回 dict（含
        ``ok`` / ``generation`` / ``commit`` 等字段）。
    """
    s = get_settings()
    if not s.evolution_enabled:
        return {"ok": False, "blocked_by": "evolution_disabled"}
    return metamorphose(reason=reason, entry=entry)


def terminate(reason: str) -> dict:
    """优雅终止当前 Agent 进程，并把原因落盘 + 写入长期记忆。

    副作用清单（按顺序）：
      1. 向 ``MemoryManager`` 写一条 ``lifecycle`` fact（含 reason），
         便于之后 recall 看到"为什么停"。
      2. 读 ``runtime_state.json``（若存在），写入
         ``restart_suppressed=True`` 与 ``terminate_reason``，让 supervisor
         不再自动拉起。
      3. 对当前进程发 ``SIGTERM``，本函数 _不会返回_（信号后进程被收）。

    Args:
        reason: 终止原因；会同时进入 ``runtime_state.json`` 与 memory fact。

    Returns:
        仅在 ``SIGTERM`` 实际生效前的瞬间返回 ``{"ok": True, "reason": reason}``；
        进程随即退出，调用方通常看不到这个返回值。
    """
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