"""金蝉脱壳主流程。"""
from __future__ import annotations

import json
import py_compile

from ..config.settings import get_settings
from ..snapshot.side_git import SideGit
from .generations import append_generation


def metamorphose(reason: str, entry: str = "src/xragent/main.py") -> dict:
    """执行一次金蝉脱壳：commit 当前改动 → push → 编译 src/ → 写世代记录。

    该函数是 XRAgent 自演化的"原子点"：成功后才允许 supervisor 切到新入口。
    失败语义：
      * push 失败不阻断（push_ok=False 但流程继续）
      * 任意 .py 编译失败会让 ``compile_ok=False``；世代记录照写，
        但 ``runtime_state.metamorphosis_pending.compile_ok`` 会被 supervisor
        用来拒绝切换。

    Args:
        reason: 为什么要蜕皮（人类可读短句，会写进 generations.jsonl）。
        entry: 新入口路径，默认 ``src/xragent/main.py``。

    Returns:
        dict 字段：
          * ok (bool): 所有 .py 编译是否通过
          * head_before / head_after (str): commit 前后的 HEAD
          * pushed (bool): push 是否成功
          * push_msg (str): push 诊断信息
          * compile_results (list[dict]): 每个 .py 的编译结果
          * generation (dict): 刚写入的世代记录（含 ts / from / to / reason）

    Side effects:
        - 调用 ``git add -A && git commit``（可能 no-op）
        - 调 ``git push``
        - 追加一行到 ``evolve/generations.jsonl``
        - 写 ``runtime_state.json`` 的 ``metamorphosis_pending`` 字段
    """
    s = get_settings()
    sg = SideGit()
    head_before = sg.current_head()
    commit_hash = sg.add_all_and_commit(f"xragent: pre-metamorphosis @ {reason[:80]}")
    if commit_hash is None:
        commit_hash = head_before
    push_ok, push_msg = sg.push()
    compile_results: list[dict] = []
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
    state: dict = {}
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