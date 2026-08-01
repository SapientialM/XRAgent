"""git 工具:commit / push。

**v0.5.4 timeout**:
  - ``git_push`` 加 ``timeout_s`` 参数（默认 30s，与 ``exec_tools`` 一致）。
    此前 ``git push`` 直接调 ``subprocess.run`` 无 timeout,网络卡住或 SSH
    挂起会让 LLM 工具调用无限阻塞,直到外层 ReAct 循环超时。修法:
      * 抽 ``_fail(msg, **extras)`` 统一 ``ok=False`` 字典(注意: 本工具用
        ``msg`` 键, 与 ``exec_tools._fail`` 用的 ``error`` 键不同 —— 是
        test_git_tools_timeout.py:81 / test_exec_tools.py:216 锁住的
        有意契约分歧, 不要合并)
      * ``_resolve_timeout(value, *, default) -> int`` 现在委托给
        :func:`xragent.tools.exec_tools._coerce_int` (后者已被
        ``run_cmd`` / ``_truncate_output`` 共用, 是真正的公共 helper)。
        保留 ``(value, *, default)`` 形式仅为兼容 test_git_tools_timeout.py
        里 8 条直接调用 ``git_tools._resolve_timeout(..., default=N)`` 的断言。
      * 捕获 ``subprocess.TimeoutExpired`` 转 ``ok=False, msg="超时（>{t}s）"``
      * 捕获 ``FileNotFoundError`` / ``OSError`` 转 ``ok=False, msg="<type>: <e>"``

**v0.5.5 snapshot_cleanup**: 加 ``snapshot_cleanup`` 薄包装,把
``SideGit.cleanup_old_snapshots`` 暴露成 ``medium`` 风险工具 (只动本地
``xragent/turn-*`` tag, 不走网络, tag 从 commit 可恢复 — 不需要 HITL
审批)。该函数本体已在 ``tests/test_sidegit_cleanup.py`` 锁住,本文件
只新增包装层 + 1 条工具契约测试。
"""
from __future__ import annotations

import subprocess
from typing import Any

from ..snapshot.side_git import SideGit
from .exec_tools import _coerce_int


# === 常量：与 exec_tools 对齐，便于两处工具 timeout 行为一致 ===
DEFAULT_PUSH_TIMEOUT_S: int = 30


def _fail(msg: str, /, **extras: Any) -> dict[str, Any]:
    """``ok=False`` 字典工厂。``msg`` 是 positional-only 必填;

    ``**extras`` 显式传入才出现,默认空。LLM 工具契约要求最小键集,
    不要随便往 extras 里塞字段。
    """
    out: dict[str, Any] = {"ok": False, "msg": msg}
    out.update(extras)
    return out


def _resolve_timeout(value: object, *, default: int) -> int:
    """归一化 timeout 输入到合法正整数。

    委托给 :func:`xragent.tools.exec_tools._coerce_int`, 与 ``run_cmd``
    / ``_truncate_output`` 走同一份兜底矩阵 (None / bool / 非数值 /
    非正数 → default)。``min_value=1`` 保证 ``0`` 也走 fallback —— 与
    原版 ``value <= 0 → default`` 语义一致。

    保留 ``(value, *, default)`` 签名仅为兼容 test_git_tools_timeout.py
    里 ``git_tools._resolve_timeout(None, default=30)`` 等 8 条直接调用。
    """
    return _coerce_int(value, default, min_value=1)


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


def git_push(
    remote: str = "origin",
    branch: str = "main",
    timeout_s: int | float | None = DEFAULT_PUSH_TIMEOUT_S,
) -> dict[str, Any]:
    """把当前 HEAD push 到 ``<remote>/<branch>``。

    失败(无 origin / 鉴权失败 / 网络断 / **超时**)时返回 ``ok=False, msg=<诊断>``,
    不会抛异常 —— LLM 拿到结果后自己决定重试 / 放弃 / 报警。成功的
    push 在 ``msg=""``(git push 成功时 stderr/stdout 通常为空)。

    Args:
        remote: 远端名;默认 ``"origin"``,与 ``SideGit.push`` 默认一致
            (test_git_tools.py::test_git_push_default_remote_branch_is_origin_main 锁)。
        branch: 分支名;默认 ``"main"``。
        timeout_s: push 超时秒数。``None`` / 非数值 / 非正数 → 默认 30s。
            超时不会抛异常,而是返回 ``ok=False, msg="超时（>{t}s）: ..."``。
            这一层兜底是为防止网络卡住时 LLM 工具调用无限阻塞 —— 之前
            ``subprocess.run`` 不带 timeout,SSH 鉴权挂起会让 ReAct 循环
            等到外层超时才返回。

    Returns:
        严格只含 2 个键的 dict(LLM 工具契约,test_git_tools.py 锁定):
            * ``ok`` (bool): True 表示 push 成功 (rc == 0)
            * ``msg`` (str): 失败时是 stderr(或 stdout) 的诊断信息;
                成功时为空字符串。绝对非空当 ``ok=False`` 时。
    """
    effective_timeout = _resolve_timeout(timeout_s, default=DEFAULT_PUSH_TIMEOUT_S)

    sg = SideGit()
    try:
        result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=str(sg.root),
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as e:
        return _fail(
            f"超时（>{effective_timeout}s）",
            timed_out=True,
        )
    except (FileNotFoundError, OSError) as e:
        return _fail(f"{type(e).__name__}: {e}")

    return {
        "ok": result.returncode == 0,
        "msg": (result.stderr or result.stdout).strip(),
    }


def snapshot_cleanup(
    max_age_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """清理 N 天前的 ``xragent/turn-*`` snapshot tag（薄包装）。

    委托给 :meth:`SideGit.cleanup_old_snapshots` — 该方法的完整契约
    (仅命中 ``xragent/turn-*`` 前缀 / ``<=0`` 禁用 / ``dry_run`` 仅列候选
    / 非 git 仓库静默返 ``[]``) 已在 ``tests/test_sidegit_cleanup.py``
    里锁住。本函数只负责把返回值包成 LLM 工具契约字典 + 异常兜底。

    风险等级 ``medium``: 只动本地 git tag, 不走网络, tag 从 commit hash
    可恢复 (``git tag <name> <commit>``), 默认 30 天保留, 不需要 HITL
    审批。Agent 可随时调用做日常维护。

    Args:
        max_age_days: 保留天数; ``None`` 走
            :attr:`Settings.snapshot_retention_days` (默认 30)。
            ``<= 0`` 在 SideGit 层会被禁用并返回空列表。
        dry_run: True 仅列候选 tag, 不实际删除。

    Returns:
        严格只含 3 个键的 dict (LLM 工具契约):
            * ``ok`` (bool): True 表示调用成功完成 (即使没删任何 tag)
            * ``removed`` (list[str]): 被删除的 tag 名列表 (按 creatordate
                旧→新排序); ``dry_run=True`` 时是候选列表
            * ``dry_run`` (bool): 透传输入, 便于 LLM 区分 "预览" vs "实删"
    """
    try:
        removed = SideGit().cleanup_old_snapshots(
            max_age_days=max_age_days,
            dry_run=dry_run,
        )
    except Exception as e:  # noqa: BLE001 - 兜底转 ok=False
        return _fail(f"{type(e).__name__}: {e}")
    return {"ok": True, "removed": list(removed), "dry_run": dry_run}