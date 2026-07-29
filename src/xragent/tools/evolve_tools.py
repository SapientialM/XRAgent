"""蜕皮 + terminate 工具。"""
from __future__ import annotations

import json
import os
import signal
from typing import Any

from ..evolve.metamorphosis import metamorphose
from ..config.settings import get_settings


def propose_self_replace(reason: str, entry: str = "src/xragent/main.py") -> dict[str, Any]:
    """请求"金蝉脱壳":Agent 自审后把新一代源码 commit → push → supervisor 切换。

    实际逻辑委托给 :func:`xragent.evolve.metamorphosis.metamorphose`, 本工具
    只多一道"evolution enabled"门控: 当 settings 把 ``XRAGENT_EVOLUTION_ENABLED``
    关掉(父母 --freeze)时, 直接返回 ``{"ok": False, "blocked_by": "evolution_disabled"}``,
    不进入蜕皮流程。

    Args:
        reason: 蜕皮理由,会写入 ``evolve/generations.jsonl`` 一行。
        entry: 新一代入口模块路径(传给 metamorphose);默认
            ``"src/xragent/main.py"`` —— 通常改的是入口;若改的是某个
            子模块,这里传它也行(contract 由 metamorphose 决定)。

    Returns:
        dict 形状由 ``metamorphose`` 决定,常见键:
            * ``ok`` (bool): 是否走完 commit+push+compile 全流程
            * ``compile_results`` (list[dict]): py_compile 逐文件结果
            * ``generation`` (dict): 写入 generations.jsonl 的那条记录
            * ``head_after`` (str | None): 蜕皮后 HEAD sha

        当 evolution 关闭时, 返回 ``{"ok": False, "blocked_by": "evolution_disabled"}``。

    Note:
        成功路径会以 SIGTERM 杀掉当前进程让 supervisor 切到新 entry;返回的
        dict 在 supervisor 接管后通常 *不可达*, 这里写返回主要是给日志兜底。
    """
    s = get_settings()
    if not s.evolution_enabled:
        return {"ok": False, "blocked_by": "evolution_disabled"}
    return metamorphose(reason=reason, entry=entry)


def terminate(reason: str) -> dict[str, Any]:
    """优雅终止当前 Agent 进程。

    写一条 ``category="lifecycle"`` 的 memory fact(供之后回溯"为什么挂掉"),
    把 ``runtime_state.json`` 的 ``restart_suppressed=True`` 置位(让 supervisor
    不要自动拉起 —— 这是一次"父亲要求停下",不是崩溃), 然后给当前进程发
    SIGTERM。

    Args:
        reason: 终止原因;会被写入 memory fact + runtime_state.json
            的 ``terminate_reason`` 字段。

    Returns:
        ``{"ok": True, "reason": <reason>}`` —— 实际进程已被 SIGTERM 杀掉,
        这个返回值通常 *不可达*, 是给主循环 / 测试用的兜底。

    Note:
        本工具对应 DREAM 第五节"最终开关";只有连续多轮验证为不可恢复的
        失控时才应调用。
    """
    s = get_settings()
    from ..memory.manager import MemoryManager
    m = MemoryManager()
    m.save_fact(category="lifecycle", content=f"terminate: {reason}", source_turn="agent")
    runtime = s.repo_root / "runtime_state.json"
    state: dict[str, Any] = {}
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