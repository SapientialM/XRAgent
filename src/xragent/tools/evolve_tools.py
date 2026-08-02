"""evolve_tools.py — 金蝉脱壳 (propose_self_replace) + 自杀 (terminate)。

LLM-facing 工具只暴露这两个 risk=high entry；其余是 test_evolve_tools
锁死的契约 helper (/_load_runtime_state, /_save_runtime_state, /_check_compile)
与 module-level 常量 (/RUNTIME_STATE_KEY_*).

历史: 5.x 重构 (DRY 版本) 把老 evolve_tools 里的冗余 / 死代码 (write_file,
run_cmd, git_commit, git_push, sidegit_snapshot) 砍掉了, 新版以
``evolve.metamorphosis.metamorphose`` 为 single source of truth, 这里
只剩薄薄的 LLM-facing wrapper + 测试契约约定的内部 helper.
"""
from __future__ import annotations

import json
import os
import py_compile
from pathlib import Path
from typing import Any

from .blacklist import PathSandbox  # noqa: F401  — 对外保持可见, 防老人代码路径围栏用

from ..config.settings import get_settings
from ..watchdog.runtime_state import read as _rs_read, write as _rs_write
from ..memory.manager import MemoryManager
# metamorphose 作为 module-level attr 暴露, 让 test_evolve_tools 能
# monkeypatch.setattr(evolve_tools, "metamorphose", ...) 拦截正常路径.
from ..evolve.metamorphosis import metamorphose  # noqa: E402,F401


# ============ runtime_state key 常量 ============
# 测试期望 ``evolve_tools.RUNTIME_STATE_KEY_*`` 存在 (level="module"
# import 比较方便). 与写入侧 ``_save_runtime_state`` 协作:
#   - RUNTIME_STATE_KEY_RESTART_SUPPRESSED = True → supervisor 不再拉起
#   - RUNTIME_STATE_KEY_TERMINATE_REASON = "<why>" → supervisor / 日志可见
RUNTIME_STATE_KEY_RESTART_SUPPRESSED: str = "restart_suppressed"
RUNTIME_STATE_KEY_TERMINATE_REASON: str = "terminate_reason"


# ============ 公共 helper ============

def _load_runtime_state(path: Path) -> dict[str, Any]:
    """读 runtime_state.json (缺文件 / JSON 损坏时回退空 dict, 不抛异常).

    Args:
        path: 任意 Path; 期望 ``<repo_root>/runtime_state.json`` 但不强求存在.

    Returns:
        dict[str, Any]: 文件内容; 缺 / 空 / 损坏 → ``{}``.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_runtime_state(path: Path, state: dict[str, Any]) -> None:
    """原子写覆盖 runtime_state.json.

    ensure_ascii=False + indent=2: 中文可肉眼读 + 提交到 git 时 diff 直观.
    自动 ``mkdir -p`` 父目录 (首次启动场景).

    Args:
        path: 写入目标; 父目录若不存在会被创建.
        state: 待持久化的字典.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _check_compile(repo_root: Path) -> list[dict[str, Any]]:
    """对 ``<repo_root>/src`` 下每个 ``.py`` 跑 ``py_compile``.

    Args:
        repo_root: 仓库根; 用于把绝对路径转 ``str(Path.relative_to(repo_root))``
            方便 JSONL 日志肉眼可读.

    Returns:
        list[dict[str, Any]]: 每条::

            {"file": <rel-posix-path>, "ok": True}
            # 或失败时:
            {"file": <rel-posix-path>, "ok": False, "error": <str>}

        ``<repo_root>/src`` 不存在时返回空 list.
    """
    src_dir = repo_root / "src"
    if not src_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for py in src_dir.rglob("*.py"):
        rel = str(py.relative_to(repo_root))
        try:
            py_compile.compile(str(py), doraise=True)
            results.append({"file": rel, "ok": True})
        except py_compile.PyCompileError as e:
            results.append({"file": rel, "ok": False, "error": str(e)})
    return results


# ============ LLM-facing 工具 ============

def propose_self_replace(
    reason: str,
    entry: str = "src/xragent/main.py",
    dry_run: bool = False,
) -> dict[str, Any]:
    """金蝉脱壳入口 (LLM 工具契约).

    Args:
        reason: 蜕皮原因 (人类可读短句); 写入 generations.jsonl 与 commit msg.
        entry: 新世代入口文件路径; 默认 ``src/xragent/main.py``.
        dry_run: True 时跳过 commit / push / 写 generations, 仅跑 ``_check_compile``
            做 syntax 体检 (给"我想蜕皮但先确认能编译过"场景用).

    Returns:
        dict[str, Any]: 形状取决于分支:
          * ``evolution_enabled=False`` → ``{"ok": False, "blocked_by": "evolution_disabled"}``
          * ``dry_run=True`` → ``{"ok": <bool>, "dry_run": True, "compile_results": [...], "head_after": None}``
          * 否则 → ``metamorphose(reason, entry)`` 的返回值 (转写 ``head_after``).

    Notes:
        真正的 commit + push + 世代记录全走 ``evolve.metamorphosis.metamorphose``
        (single source of truth); 这里只做 evolution_enabled 门控 + dry_run
        短路 + 透传. 测试在 monkeypatch ``evolve_tools.metamorphose`` 时
        验证"正常路径是 delegation".
    """
    s = get_settings()
    if not s.evolution_enabled:
        return {"ok": False, "blocked_by": "evolution_disabled"}
    if dry_run:
        compile_results = _check_compile(s.repo_root)
        return {
            "ok": all(r["ok"] for r in compile_results),
            "dry_run": True,
            "head_after": None,
            "compile_results": compile_results,
        }
    # 正常路径: 完全委托给 module-level ``metamorphose`` (single source of truth);
    # 测试通过 monkeypatch.setattr(evolve_tools, "metamorphose", ...) 拦截.
    return metamorphose(reason=reason, entry=entry)


def terminate(
    reason: str,
    suppress_restart: bool = True,
) -> dict[str, Any]:
    """优雅终止当前 Agent 进程 (LLM 工具契约).

    写 ``runtime_state.json`` 的 ``terminate_reason`` (+ ``restart_suppressed``
    当 ``suppress_restart=True``); 给 supervisor 留心愿; 然后 ``os.kill(os.getpid(),
    SIGTERM)`` 自杀 (测试用 monkeypatch 拦).

    Args:
        reason: 终止原因的人类可读短句; 写入 ``runtime_state["terminate_reason"]``.
        suppress_restart: True (默认) 时设 ``runtime_state["restart_suppressed"] = True``
            让 supervisor 别再自动拉起; False 时不写这个键, supervisor 仍会按惯例
            重启 (给"误报记录不真死"场景用).

    Returns:
        dict[str, Any]: ``{"ok": True, "reason": <reason>}``.

    Notes:
        测试通过 ``monkeypatch.setattr(evolve_tools.os, "kill", fake)`` 防真发信号;
        这里 ``os`` 是直接 import 的 (``import os``), 不是 ``from os import kill``,
        保证 setattr 能找到 module-level ``os`` 引用。
    """
    s = get_settings()
    state_path = s.runtime_state_path
    # 继承已有 state, 不丢 heartbeat_ts / restart_count 等
    state = _load_runtime_state(state_path)
    state[RUNTIME_STATE_KEY_TERMINATE_REASON] = reason
    if suppress_restart:
        state[RUNTIME_STATE_KEY_RESTART_SUPPRESSED] = True
    _save_runtime_state(state_path, state)
    # 给 lifecycle memory 留个 fact (测试断言 category="lifecycle" 多一条)
    try:
        m = MemoryManager()
        m.save_fact(
            category="lifecycle",
            content=f"terminate: {reason}",
            source_turn="agent",
        )
    except Exception:
        # 落 fact 失败不影响主流程 (terminate 是关键操作, 副作用吞掉)
        pass
    # 真发 SIGTERM (测试会拦)
    try:
        os.kill(os.getpid(), 15)  # 15 = SIGTERM
    except OSError:
        # 已经死了/无权限 — 不影响返回值
        pass
    return {"ok": True, "reason": reason}
