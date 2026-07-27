"""git 工具：commit / push。"""
from __future__ import annotations

from ..snapshot.side_git import SideGit


def git_commit(message: str) -> dict:
    sg = SideGit()
    head = sg.add_all_and_commit(message)
    return {"ok": True, "head": head, "no_changes": head is None}


def git_push(remote: str = "origin", branch: str = "main") -> dict:
    sg = SideGit()
    ok, msg = sg.push(remote=remote, branch=branch)
    return {"ok": ok, "msg": msg}
