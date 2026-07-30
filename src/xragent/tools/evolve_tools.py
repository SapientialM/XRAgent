"""evolve_tools.py — DRY version (consolidated to reduce surface area).

External entry points (back-compat names): propose_self_replace, terminate,
git_commit, write_file, run_cmd.  All other helpers are private.

**typing pass (v0.x)**：把 ``sidegit_snapshot`` / ``write_file`` / ``run_cmd`` /
``git_commit`` / ``git_push`` / ``terminate`` / ``propose_self_replace`` /
``curl_url`` 八个公开函数的返回类型从裸 ``dict`` 改成 ``dict[str, Any]``，
docstring 改成 Google-style (Args / Returns / Raises)。其他内部 helper
(``_resolve`` / ``_hitl_approved``) 原本就有完整 Google-style，保持不变。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

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


def sidegit_snapshot(reason: str = "manual") -> dict[str, Any]:
    """Create a side_git snapshot for self-replace rollback safety.

    Best-effort: if side_git is unavailable or fails, return a dict
    indicating failure without raising.

    Args:
        reason: 传给 ``sidegit snapshot --reason`` 的人类可读短句；
            默认 ``"manual"``。

    Returns:
        dict[str, Any]: 成功时 ``{"ok": True, "stdout": ..., "stderr": ...}``；
        异常路径（如 ``sidegit`` 子模块不存在 / 进程崩溃）::

            {"ok": False, "stdout": "...", "stderr": "..."}
            # 或
            {"ok": False, "error": "<异常 repr>"}

        永远不会抛异常；调用方拿到 ``ok=False`` 应自行降级。
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


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write file in-repo; refuses on blacklist or out-of-tree path.

    Args:
        path: 仓库内相对路径或绝对路径；解析后必须在 :data:`_REPO_ROOT` 子树内。
        content: 写入的 UTF-8 文本；空串也允许。

    Returns:
        dict[str, Any]: 成功时::

            {"ok": True, "path": "<相对 repo 的 POSIX 路径>", "size": <bytes>}

        失败时（黑名单 / 只读 / 逃出 repo）抛 :class:`PermissionError`，
        由上层 LLM 工具调用层捕获并转 ``ok=False``。
    """
    p = _resolve(path)
    rel = str(p.relative_to(_REPO_ROOT))
    _blacklist_check(rel)
    if rel in _READ_ONLY:
        raise PermissionError(f"read-only path: {rel}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": rel, "size": len(content)}


def run_cmd(cmd: str) -> dict[str, Any]:
    """Run shell command in repo root with binary blacklist.

    Args:
        cmd: shell 字符串；第一段（按空白切）若落在 :data:`BLOCKED_BINARIES`
            则直接拒掉（防 ``curl`` / ``wget`` / ``ssh`` / ``nc`` 等）。

    Returns:
        dict[str, Any]: 始终带 ``hitl_approved: True``；成功时::

            {"ok": True, "returncode": 0, "stdout": "...", "stderr": "...",
             "hitl_approved": True}

        stdout / stderr 各截断到 ``4000`` / ``2000`` 字符尾部，避免 LLM 上下文爆炸。
        30 秒超时返回 ``{"ok": False, "error": "timeout (30s)"}``。

    Raises:
        PermissionError: ``HITL_APPROVED != "1"`` 或首段 binary 在黑名单。
    """
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


def git_commit(message: str) -> dict[str, Any]:
    """``git add -A`` + ``git commit -m <message>`` with HITL guard.

    Args:
        message: commit message；空串会 git 报错，由返回字段 ``stderr`` 透传。

    Returns:
        dict[str, Any]: 成功时::

            {"ok": True, "returncode": 0, "stdout": "...", "stderr": "...",
             "commit": "<40-char hex HEAD>"}

        ``git add -A`` 失败时::

            {"ok": False, "stage_stderr": "..."}

        ``git commit`` 失败时仍带 ``commit: "<空仓库时可能为空>"``。

    Raises:
        PermissionError: ``HITL_APPROVED != "1"`` 时拒掉。
    """
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


def git_push(remote: str = "origin", branch: str = "main") -> dict[str, Any]:
    """``git push <remote> <branch>`` with HITL guard.

    Args:
        remote: 远端名，默认 ``origin``。
        branch: 分支名，默认 ``main``。

    Returns:
        dict[str, Any]::

            {"ok": <bool>, "returncode": <int>,
             "stdout": "...", "stderr": "..."}

        network/auth 失败时 ``ok=False`` 且 ``stderr`` 含 git 报错摘要。

    Raises:
        PermissionError: ``HITL_APPROVED != "1"`` 时拒掉。
    """
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


def terminate(reason: str) -> dict[str, Any]:
    """Mark agent for graceful termination (HITL required).

    写 :data:`runtime_state` 的 ``terminate_requested`` / ``terminate_reason``；
    supervisor 下一个心跳会拉起关闭流程。

    Args:
        reason: 终止原因的人类可读短句，写入 ``runtime_state["terminate_reason"]``。

    Returns:
        dict[str, Any]: ``{"ok": True, "reason": <reason>}``。

    Raises:
        PermissionError: ``HITL_APPROVED != "1"`` 时拒掉（防止 LLM 误触 terminate）。
    """
    if not _hitl_approved():
        raise PermissionError("terminate requires HITL approval")
    from ..state import runtime_state
    runtime_state["terminate_requested"] = True
    runtime_state["terminate_reason"] = reason
    return {"ok": True, "reason": reason}


def propose_self_replace(reason: str, entry: str = "src/xragent/main.py") -> dict[str, Any]:
    """DRY: write reason → snapshot → git_commit → push → write new entry.

    Real self-replace still needs HITL; here we just orchestrate the
    safe side-git + commit + push sequence so higher-level callers
    don't repeat the dance.

    Args:
        reason: 蜕皮原因；同时写到 commit message + side_git snapshot --reason。
        entry: 入口文件路径（占位参数；真正的金蝉脱壳流程由 supervisor 走）。

    Returns:
        dict[str, Any]::

            {
              "ok": <bool>,                  # git_commit 成功与否
              "snapshot": {...},             # sidegit_snapshot 结果
              "commit": {...},               # git_commit 结果
              "push": {...} | None,          # commit 失败时为 None
              "entry": "<entry 参数>",
            }

    Raises:
        PermissionError: 任何一步要求 HITL 但未审批时由子函数抛出。
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


def curl_url(url: str, method: str = "GET", data: str = "") -> dict[str, Any]:
    """HTTP GET/POST with 5min rate limit + diary logging.

    Args:
        url: 目标 URL；走 ``urllib.request``，无代理设置。
        method: HTTP method，默认 ``GET``。
        data: POST body；空串走 GET，非空自动 ``.encode()``。

    Returns:
        dict[str, Any]: 成功时::

            {"ok": True, "status": <http code>, "body": <前 8000 字符>}

        5 分钟内重复调用返回（不实际发请求）::

            {"ok": False, "error": "rate_limited",
             "retry_after": <距离下次允许的秒数>}

        其他网络异常返回 ``{"ok": False, "error": "<异常 repr>"}``。
        任何成功响应会写一行到 ``diary/search-log.md``（失败静默吞掉）。

    Raises:
        PermissionError: ``HITL_APPROVED != "1"`` 时拒掉。
    """
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