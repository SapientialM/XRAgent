"""金蝉脱壳主流程。"""
from __future__ import annotations

import json
import py_compile
from typing import Any

from ..config.settings import get_settings
from ..snapshot.side_git import SideGit
from .generations import append_generation


def metamorphose(reason: str, entry: str = "src/xragent/main.py") -> dict[str, Any]:
    """执行一次金蝉脱壳：commit → push → py_compile → 写 generations.jsonl。

    流程固定为 4 步，与 supervisor / evolve_tools 的调用方契约一致：
      1. ``SideGit`` 拿到当前 HEAD；
      2. ``add_all_and_commit`` 提交一次（无变更时返回 ``None``，回退到旧 HEAD）；
      3. ``push`` 推 origin；若网络失败 ``push_ok=False``，仍继续（本地记录已生成）；
      4. 对 ``src/`` 下每个 ``.py`` 跑 ``py_compile``，全部 ok 才算 compile_ok；
      5. ``append_generation`` 写世代记录，并通过 ``runtime_state.json`` 写入
         ``metamorphosis_pending`` 给 supervisor 触发进程替换。

    Args:
        reason: 为什么要蜕皮（人类可读短句；会进 generations.jsonl 的 reason
            字段，并在 commit message 中截断到 80 字符）。
        entry: 新世代入口文件路径（相对 ``repo_root``）；默认 ``src/xragent/main.py``。
            写入 generations 记录的 ``extra.entry``，给 supervisor 用来校验入口存在。

    Returns:
        dict[str, Any]: 包含以下键的结果摘要：
          * ``ok`` (bool): 所有 ``.py`` 都 py_compile 通过；
          * ``head_before`` (str | None): commit 前的 HEAD；
          * ``head_after`` (str | None): 实际 commit 后的 HEAD（无变更时退回 ``head_before``）；
          * ``pushed`` (bool): push 是否成功；
          * ``push_msg`` (str): push 的原始错误信息（成功时为 ``""``）；
          * ``compile_results`` (list[dict[str, Any]]): 每个 ``.py`` 的编译结果；
          * ``generation`` (dict[str, Any]): 写入 generations.jsonl 的那一行。
    """
    s = get_settings()
    sg = SideGit()
    head_before = sg.current_head()
    commit_hash = sg.add_all_and_commit(f"xragent: pre-metamorphosis @ {reason[:80]}")
    if commit_hash is None:
        commit_hash = head_before
    push_ok, push_msg = sg.push()
    compile_results: list[dict[str, Any]] = []
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
    state: dict[str, Any] = {}
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