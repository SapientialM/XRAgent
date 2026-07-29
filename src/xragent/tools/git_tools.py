"""git 工具：commit / push。"""
from __future__ import annotations

from ..snapshot.side_git import SideGit


def git_commit(message: str) -> dict:
    """Agent 显式调用 git_commit → 必须 commit（即使改动很小）。

    与 SideGit.add_all_and_commit 的默认 min_diff_bytes=100 解耦：
    内部护栏是给 main.py / metamorphosis.py 这些自动 commit 路径用的
    (防止 Agent 写一行注释就刷屏)；但 Agent 主动调 git_commit 工具时,
    只要有改动就应当 commit, 不论行数多少 (test_git_tools.py 锁定此契约)。
    """
    sg = SideGit()
    head = sg.add_all_and_commit(message, min_diff_bytes=0)
    return {"ok": True, "head": head, "no_changes": head is None}


def git_push(remote: str = "origin", branch: str = "main") -> dict:
    sg = SideGit()
    ok, msg = sg.push(remote=remote, branch=branch)
    return {"ok": ok, "msg": msg}
