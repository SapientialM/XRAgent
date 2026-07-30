"""金蝉脱壳主流程。"""
from __future__ import annotations

import py_compile
from pathlib import Path

from ..config.settings import get_settings
from ..snapshot.side_git import SideGit
from ..watchdog.runtime_state import read as _rs_read, write as _rs_write
from .generations import append_generation


def _compile_one(py: Path, repo_root: Path) -> dict:
    """py_compile 单个文件，返回 ``{"file": rel, "ok": bool, [error]: str}``。

    把 ``try/except PyCompileError`` 与 ``relative_to`` 收敛到一处；
    之前 ``metamorphose`` 主体里两段近乎对称的字典构造在此合一。
    """
    rel = str(py.relative_to(repo_root))
    try:
        py_compile.compile(str(py), doraise=True)
        return {"file": rel, "ok": True}
    except py_compile.PyCompileError as e:
        return {"file": rel, "ok": False, "error": str(e)}


def metamorphose(reason: str, entry: str = "src/xragent/main.py") -> dict:
    s = get_settings()
    sg = SideGit()
    head_before = sg.current_head()
    commit_hash = sg.add_all_and_commit(f"xragent: pre-metamorphosis @ {reason[:80]}")
    if commit_hash is None:
        commit_hash = head_before
    push_ok, push_msg = sg.push()
    compile_results = [
        _compile_one(py, s.repo_root) for py in (s.repo_root / "src").rglob("*.py")
    ]
    compile_ok = all(r["ok"] for r in compile_results)
    rec = append_generation(
        from_head=commit_hash, to_ref=commit_hash, reason=reason,
        extra={"entry": entry, "push_ok": push_ok, "compile_ok": compile_ok},
    )
    # runtime_state.json 复用 watchdog.runtime_state 的 atomic 读写封装
    # (之前 inline json.loads + try/except + raw write, 与 watchdog 重复)
    state = _rs_read()
    state["metamorphosis_pending"] = {
        "ts": rec["ts"], "reason": reason, "new_head": commit_hash,
        "entry": entry, "compile_ok": compile_ok,
    }
    _rs_write(state)
    return {
        "ok": compile_ok, "head_before": head_before, "head_after": commit_hash,
        "pushed": push_ok, "push_msg": push_msg, "compile_results": compile_results, "generation": rec,
    }