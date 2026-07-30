"""git 工具:commit / push。"""
from __future__ import annotations

from typing import Any, Final, TypedDict

from ..snapshot.side_git import SideGit


# === 常量：暴露给测试 / 外部调用方统一引用 ===
# 0 表示"不设门槛"，与 SideGit.add_all_and_commit(min_diff_bytes=100) 默认行为不同:
# Agent 显式调 git_commit 应该尽量 commit，所以这里默认 0。
DEFAULT_MIN_DIFF_BYTES: Final[int] = 0
# 上界：防止 Agent 传巨大数挂死 `git diff --shortstat` 统计。
MIN_DIFF_BYTES_UPPER_BOUND: Final[int] = 100_000


class GitCommitResult(TypedDict):
    """``git_commit`` 的 LLM 工具契约返回结构（test_git_tools.py 锁键集）。

    Keys:
        ok: 始终为 ``True``（底层异常已包成 ``no_changes=True``）。
        head: 新 commit 的 sha；无改动 / 被护栏跳过时为 ``None``。
        no_changes: ``True`` 表示本次没有产生 commit（幂等语义）。
    """

    ok: bool
    head: str | None
    no_changes: bool


# === 内部 helpers（暴露给白盒测试） ===


def _normalize_min_diff_bytes(
    value: Any,
    *,
    default: int = DEFAULT_MIN_DIFF_BYTES,
) -> int:
    """归一化 ``min_diff_bytes`` 到 ``[default, MIN_DIFF_BYTES_UPPER_BOUND]``。

    处理六种异常输入 → 全部稳态到合理值：

    * ``None`` / ``bool``（``bool`` 是 ``int`` 子类，``True``/``False`` 容易被误用）
      → 走 ``default``
    * 负数 / 0 → 走 ``default``（Agent 不应被允许传 ≤0 跳过护栏到 < 0 的负数区间）
    * ``str`` / ``list`` / ``dict`` 等非数值 → 尝试 ``int(value)``，失败走 ``default``
    * 超过 ``MIN_DIFF_BYTES_UPPER_BOUND`` → 上界 clamp，防 Agent 传巨大数挂死 diff 统计
    * ``float`` → ``int()`` 截断

    Args:
        value: Agent 传入的原始值（接受任意类型）
        default: 兜底值，默认 ``DEFAULT_MIN_DIFF_BYTES``（=0）

    Returns:
        合法 ``[0, MIN_DIFF_BYTES_UPPER_BOUND]`` 区间内的整数
    """
    # bool 必须在 int 检查之前排除（isinstance(True, int) == True）
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        if value <= 0:
            return default
        return min(value, MIN_DIFF_BYTES_UPPER_BOUND)
    if isinstance(value, float):
        if value <= 0:
            return default
        return min(int(value), MIN_DIFF_BYTES_UPPER_BOUND)
    # str / list / dict 等：尝试强转；失败回 default
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if n <= 0:
        return default
    return min(n, MIN_DIFF_BYTES_UPPER_BOUND)


def _commit_result(head: str | None) -> dict[str, Any]:
    """把 ``SideGit.add_all_and_commit`` 的 head 包装成 3 键 LLM 契约 dict。

    ``head is None``（被护栏跳过 / 无改动） → ``no_changes=True``
    ``head`` 是 sha 字符串（成功 commit）→ ``no_changes=False``

    严格不变量（test_git_tools.py::test_git_commit_return_dict_has_exactly_expected_keys 锁）：

    * 键集恒为 ``{"ok", "head", "no_changes"}``
    * ``ok`` 恒为 ``True``
    """
    return {"ok": True, "head": head, "no_changes": head is None}


# === 公共 API ===


def git_commit(
    message: str,
    *,
    min_diff_bytes: int | None = None,
) -> dict[str, Any]:
    """Agent 显式调用 git_commit → 必须 commit(即使改动很小)。

    与 ``SideGit.add_all_and_commit`` 的默认 ``min_diff_bytes=100`` 解耦:
    内部护栏是给 main.py / metamorphosis.py 这些自动 commit 路径用的
    (防止 Agent 写一行注释就刷屏);但 Agent 主动调 git_commit 工具时,
    只要有改动就应当 commit, 不论行数多少 (test_git_tools.py 锁定此契约)。

    Args:
        message: 透传给 ``git commit -m`` 的消息原文;支持空格 / 冒号 / 括号
            / 中文 / emoji, 不做引号转义 —— shell=True 的 git 进程会处理。
        min_diff_bytes: 改动门槛 (ins+dels 行数之和)。``None`` / 负数 / 0 /
            ``bool`` / 不可强转 / 超过 ``MIN_DIFF_BYTES_UPPER_BOUND`` 都被
            ``_normalize_min_diff_bytes`` 兜底到 ``DEFAULT_MIN_DIFF_BYTES``(=0)。
            Agent 想"改动达到 N 行才 commit" 时显式传入正整数即可。

    Returns:
        严格只含 3 个键的 dict(LLM 工具契约,test_git_tools.py 锁定):
            * ``ok`` (bool): 始终为 True(底层异常已转成 ``no_changes=True``)
            * ``head`` (str | None): 新 commit 的 sha;无改动时为 None
            * ``no_changes`` (bool): True 表示本次没有产生 commit(幂等语义)
    """
    sg = SideGit()
    effective_min = _normalize_min_diff_bytes(min_diff_bytes)
    head = sg.add_all_and_commit(message, min_diff_bytes=effective_min)
    return _commit_result(head)


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
