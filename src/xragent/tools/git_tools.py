"""git 工具:commit / push。"""
from __future__ import annotations

from typing import Any

from ..snapshot.side_git import SideGit


def git_commit(message: str) -> dict[str, Any]:
    """Agent 显式调用 git_commit → 必须 commit(即使改动很小)。

    与 ``SideGit.add_all_and_commit`` 的默认 ``min_diff_bytes=100`` 解耦:
    内部护栏是给 main.py / metamorphosis.py 这些自动 commit 路径用的
    (防止 Agent 写一行注释就刷屏);但 Agent 主动调 git_commit 工具时,
    只要有改动就应当 commit, 不论行数多少 (test_git_tools.py 锁定此契约)。

    Args:
        message: 透传给 ``git commit -m`` 的消息原文;支持空格 / 冒号 / 括号
            / 中文 / emoji, 不做引号转义 —— shell=True 的 git 进程会处理。

    Returns:
        严格只含 3 个键的 dict(LLM 工具契约,test_git_tools.py 锁定):
            * ``ok`` (bool): 始终为 True(底层异常已转成 ``no_changes=True``)
            * ``head`` (str | None): 新 commit 的 sha;无改动时为 None
            * ``no_changes`` (bool): True 表示本次没有产生 commit(幂等语义)
    """
    sg = SideGit()
    head = sg.add_all_and_commit(message, min_diff_bytes=0)
    return {"ok": True, "head": head, "no_changes": head is None}


def git_push(remote: str = "origin", branch: str = "main") -> dict[str, Any]:
    """把当前 HEAD push 到 ``<remote>/<branch>``。

    失败(无 origin / 鉴权失败 / 网络断)时返回 ``ok=False, msg=<诊断信息>``,
    不会抛异常 —— LLM 拿到结果后自己决定重试 / 放弃 / 报警。成功的
    push 在 ``msg=""``(git push 成功时 stderr/stdout 通常为空)。

    Args:
        remote: 远端名;默认 ``"origin"``,与 ``SideGit.push`` 默认一致
            (test_git_tools.py::test_git_push_default_remote_branch_is_origin_main 锁)。
        branch: 分支名;默认 ``"main"``。

    Returns:
        严格只含 2 个键的 dict(LLM 工具契约,test_git_tools.py 锁定):
            * ``ok`` (bool): True 表示 push 成功 (rc == 0)
            * ``msg`` (str): 失败时是 stderr(或 stdout) 的诊断信息,
                成功时为空字符串。绝对非空当 ``ok=False`` 时。
    """
    sg = SideGit()
    ok, msg = sg.push(remote=remote, branch=branch)
    return {"ok": ok, "msg": msg}