"""金蝉脱壳主流程。"""
from __future__ import annotations

import json
import py_compile

from ..config.settings import get_settings
from ..snapshot.side_git import SideGit
from .generations import append_generation


def metamorphose(reason: str, entry: str = "src/xragent/main.py") -> dict:
    s = get_settings()
    sg = SideGit()
    head_before = sg.current_head()
    commit_hash = sg.add_all_and_commit(f"xragent: pre-metamorphosis @ {reason[:80]}")
    if commit_hash is None:
        commit_hash = head_before
    push_ok, push_msg = sg.push()
    compile_results = []
    src_dir = s.repo_root / "src"
    for py in src_dir.rglob("*.py"):
        try:
            py_compile.compile(str(py), doraise=True)
            compile_results.append({"file": str(py.relative_to(s.repo_root)), "ok": True})
        except py_compile.PyCompileError as e:
            compile_results.append({"file": str(py.relative_to(s.repo_root)), "ok": False, "error": str(e)})
    compile_ok = all(r["ok"] for r in compile_results)
    rec = append_generation(
        from_head=commit_hash, to_ref=commit_hash, reason=reason,
        extra={"entry": entry, "push_ok": push_ok, "compile_ok": compile_ok},
    )
    runtime = s.repo_root / "runtime_state.json"
    state = {}
    if runtime.exists():
        try:
            state = json.loads(runtime.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state["metamorphosis_pending"] = {
        "ts": rec["ts"], "reason": reason, "new_head": commit_hash,
        "entry": entry, "compile_ok": compile_ok,
    }
    runtime.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": compile_ok, "head_before": head_before, "head_after": commit_hash,
        "pushed": push_ok, "push_msg": push_msg, "compile_results": compile_results, "generation": rec,
    }
