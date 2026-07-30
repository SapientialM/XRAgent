"""evolve_tools.py — DRY version (consolidated to reduce surface area).

External entry points (back-compat names): propose_self_replace, terminate,
git_commit, write_file, run_cmd.  All other helpers are private.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..blacklist import check as _blacklist_check
from ..config import (
    _BLACKLIST,
    _READ_ONLY,
    _REPO_ROOT,
    BLOCKED_BINARIES,
)

# ---------- internal helpers ----------


def _resolve(path: str) -> Path:
    """把任意 path 解析为绝对路径，并校验其仍在仓库根之内。

    Args:
        path: 相对或绝对路径字符串。

    Returns:
        Path: ``Path(path).resolve()`` 结果。

    Raises:
        PermissionError: 解析后路径不在 ``_REPO_ROOT`` 子树内（防逃逸）。
    """
    p = Path(path).resolve()
    root = _REPO_ROOT.resolve()
    if root not in p.parents and p != root:
        raise PermissionError(f"path escapes repo: {path}")
    return p


def _hitl_approved() -> bool:
    """检测当前进程是否被 HITL 父级放行。

    Reads:
        环境变量 ``HITL_APPROVED`` —— 等于 ``"1"`` 时返回 True（其余值/缺失均 False）。

    Returns:
        bool: 是否已审批；用于 :func:`run_cmd` / :func:`git_commit` / :func:`git_push` /
        :func:`curl_url` / :func:`terminate` 等高危操作的硬门槛。
    """
    return os.environ.get("HITL_APPROVED") == "1"


# ---------- sidegit snapshot helper ----------


def sidegit_snapshot(reason: str = "manual") -> dict:
    """Create a side_git snapshot for self-replace rollback safety.

    Best-effort: if side_git is unavailable or fails, return a dict
    indicating failure without raising.
    """
    try:
        r = subprocess.run(
            [
                "python3.11", "-m", "xragent.sidegit",
                "snapshot", "--reason", reason,
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": repr(e)}


# ---------- public wrappers ----------


def write_file(path: str, content: str) -> dict:
    """Write file in-repo; refusa on blacklist or out-of-tree path."""
    p = _resolve(path)
    rel = str(p.relative_to(_REPO_ROOT))
    _blacklist_check(rel)
    if rel in _READ_ONLY:
        raise PermissionError(f"read-only path: {rel}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": rel, "size": len(content)}


def run_cmd(cmd: str) -> dict:
    """Run shell command in repo root with binary blacklist."""
    if not _hitl_approved():
        raise PermissionError("run_cmd requires HITL approval")
    parts = cmd.split()
    if parts and parts[0] in BLOCKED_BINARIES:
        raise PermissionError(f"blocked binary: {parts[0]}")
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=30,
        )
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": r.stdout[-4000:],
            "stderr": r.stderr[-2000:],
            "hitl_approved": True,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout (30s)"}


def git_commit(message: str) -> dict:
    """git add -A + commit with HITL guard."""
    if not _hitl_approved():
        raise PermissionError("git_commit requires HITL approval")
    a = subprocess.run(
        ["git", "add", "-A"], cwd=_REPO_ROOT,
        capture_output=True, text=True, timeout=15,
    )
    if a.returncode != 0:
        return {"ok": False, "stage_stderr": a.stderr}
    c = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=20,
    )
    h = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
        capture_output=True, text=True, timeout=5,
    )
    return {
        "ok": c.returncode == 0,
        "returncode": c.returncode,
        "stdout": c.stdout,
        "stderr": c.stderr,
        "commit": h.stdout.strip(),
    }


def git_push(remote: str = "origin", branch: str = "main") -> dict:
    """git push with HITL guard."""
    if not _hitl_approved():
        raise PermissionError("git_push requires HITL approval")
    r = subprocess.run(
        ["git", "push", remote, branch],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "stdout": r.stdout, "stderr": r.stderr,
    }


def terminate(reason: str) -> dict:
    """Mark agent for graceful termination (HITL required)."""
    if not _hitl_approved():
        raise PermissionError("terminate requires HITL approval")
    from ..state import runtime_state
    runtime_state["terminate_requested"] = True
    runtime_state["terminate_reason"] = reason
    return {"ok": True, "reason": reason}


def propose_self_replace(reason: str, entry: str = "src/xragent/main.py") -> dict:
    """DRY: write reason → snapshot → git_commit → push → write new entry.

    Real self-replace still needs HITL; here we just orchestrate the
    safe side-git + commit + push sequence so higher-level callers
    don't repeat the dance.
    """
    snap = sidegit_snapshot(reason=f"self_replace: {reason}")
    commit_msg = f"propose_self_replace: {reason}\n\nsnapshot_ok={snap.get('ok')}"
    cr = git_commit(commit_msg)
    push_result = None
    if cr.get("ok"):
        push_result = git_push()
    return {
        "ok": cr.get("ok", False),
        "snapshot": snap,
        "commit": cr,
        "push": push_result,
        "entry": entry,
    }


def curl_url(url: str, method: str = "GET", data: str = "") -> dict:
    """HTTP GET/POST with 5min rate limit + diary logging."""
    if not _hitl_approved():
        raise PermissionError("curl_url requires HITL approval")
    import time
    import urllib.request
    from ..state import runtime_state, _rate_limit_lock
    with _rate_limit_lock:
        last = runtime_state.get("last_curl_ts", 0)
        now = time.time()
        if now - last < 300:
            return {"ok": False, "error": "rate_limited", "retry_after": int(300 - (now - last))}
        runtime_state["last_curl_ts"] = now
    try:
        req = urllib.request.Request(url, method=method, data=data.encode() if data else None)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            from ..diary import diary_append
            diary_append("search-log", f"curl {method} {url}\n--- response (first 500 chars) ---\n{body[:500]}")
        except Exception:
            pass
        return {"ok": True, "status": resp.status, "body": body[:8000]}
    except Exception as e:
        return {"ok": False, "error": repr(e)}
