"""git 领域包装：抽 SideGit._run / SideGit.push / main.py.maybe_periodic_push 的重复。

**起因**（v0.3 refactor 第二步）: ``util/subprocess_utils.run_capture`` 已经统一
了 "subprocess.run + capture + 超时" 这一层, 但 3 处 git 调用点都还没迁移:

  - src/xragent/snapshot/side_git.py::SideGit._run
    任意 git 命令, 非 0 raise ``RuntimeError(f"git ... 失败: ...")``
  - src/xragent/snapshot/side_git.py::SideGit.push
    ``git push <remote> <branch>``, 返回 ``(rc==0, stderr or stdout)``
  - src/xragent/main.py::cmd_autonomous.maybe_periodic_push
    ``git rev-list --count origin/main..HEAD``, 5s timeout, 失败 → 0

三个调用点的区别只在错误语义, 所以抽到 git 领域层（不直接进 subprocess_utils,
保持后者 generic）。底层仍然走 ``run_capture``; 唯一变化是把 "git" 前缀 + 错误
语义集中到一处。

**为什么不直接调用 ``run_capture``**:

  - 每个调用方都重复 ``["git", *args]`` 这个列表构造
  - ``_run`` 的 ``RuntimeError`` 消息格式 ``"git <cmd> 失败: <err>"`` 是显式契约
    (test_sidegit.py::test_side_git_run_raises_runtime_error_on_git_failure 锁住),
    散在三个调用方容易漂移

**测试影响**:

  - ``monkeypatch.setattr(side_git.subprocess, "run", fake_run)`` 还能继续拦截:
    因为 ``subprocess`` 是模块 singleton, ``run_capture`` 内 ``subprocess.run``
    是动态查找, fake_run 同样可见。``test_subprocess_utils.py`` 已锁这条。
  - ``SideGit.push`` 仍返回 ``(bool, str)``, ``SideGit._run`` 仍 raise ``RuntimeError``。
    这两条都被 ``test_sidegit.py`` 锁住, 行为不漂移就算通过。

**v0.5.7 refactor (本轮)**: ``git_run`` / ``git_count_ahead`` 边界条件收紧.

  - ``git_count_ahead`` 把 ``int(out or 0)`` 拆成"空 stdout 早返 + try int", ``or 0``
    这个 hack 在阅读时让人猜("是防 int('') 还是防 None?");显式 ``if not out:
    return 0`` 一眼看出"空输出 = 无 ahead"的边界语义。
  - ``git_run`` 错误消息加 ``rc=`` 兜底: ``RC_RUNTIME_FAIL`` (-1) 由 ``run_capture``
    在 timeout / FileNotFoundError / OSError 时返回, 此时 ``err`` 已是
    ``str(exc).strip()``, 但极端情况下若 str(e) 为空, 旧消息会变成
    ``"git X 失败: "`` 末尾空;加 ``err or f"rc={rc}"`` 让 caller 至少能看到
    returncode 这一信息维度。
"""
from __future__ import annotations

from pathlib import Path

from .subprocess_utils import RC_RUNTIME_FAIL, run_capture


def git_run(
    args: list[str] | tuple[str, ...],
    cwd: Path | str | None,
    *,
    check: bool = True,
    timeout: int | float | None = None,
) -> str:
    """Run ``git <args>`` in ``cwd``; return stripped stdout.

    Args:
        args: 透传给 git 的子命令列表 (e.g. ``["status", "--porcelain"]``)
        cwd: 工作目录; 透传给 ``run_capture`` (None = 当前进程 cwd)
        check: 若 True 且 rc != 0 (含 ``RC_RUNTIME_FAIL`` = -1), raise ``RuntimeError``;
            若 False, 失败也静默返回 stdout (可能为空)。
        timeout: ``subprocess.run`` 超时秒数

    Returns:
        stdout (已 ``.strip()``)

    Raises:
        RuntimeError: 当 ``check=True`` 且 rc != 0。消息格式
            ``"git <args> 失败: <err>"`` —— 这是 SideGit._run 旧契约,
            test_sidegit.py 锁住;err 为空时 (RC_RUNTIME_FAIL 极端情况) 兜底
            显示 ``rc=<n>``, 让 caller 至少能区分"运行失败" vs "git 命令失败"。

    Examples:
        >>> head = git_run(["rev-parse", "HEAD"], cwd=repo)
        >>> git_run(["add", "-A"], cwd=repo)  # 等价旧 SideGit._run("add", "-A")
    """
    rc, out, err = run_capture(["git", *args], cwd=cwd, timeout=timeout)
    if check and rc != 0:
        # rc 可能 == RC_RUNTIME_FAIL (-1): timeout / binary 缺失 / OS error;
        # 这时 err 是 str(e).strip(), 极端空字符串时用 rc 兜底, 避免消息末尾空。
        # SideGit._run 旧消息用 stderr.strip(), 这里 err 已是 stripped
        raise RuntimeError(f"git {' '.join(args)} 失败: {err or f'rc={rc}'}")
    return out


def git_count_ahead(
    cwd: Path | str | None,
    base: str = "origin/main",
    head: str = "HEAD",
    timeout: int | float | None = 5,
) -> int:
    """``git rev-list --count <base>..<head>`` → int。

    任意失败 (rc != 0, 解析异常, RC_RUNTIME_FAIL) → 返回 0, 不抛。

    用途: main.py::cmd_autonomous.maybe_periodic_push 检查 HEAD 是否领先 origin/main,
    只在 >0 时真正 push。原代码是 ``try/except Exception: n=0``, 这里直接抽掉
    ``try`` 因为 ``run_capture`` 内部已经把异常吞成 ``RC_RUNTIME_FAIL``。

    Examples:
        >>> n = git_count_ahead(repo)           # 0 if no remote / no ahead / any error
        >>> if n > 0:
        ...     git_push(repo)
    """
    rc, out, _ = run_capture(
        ["git", "rev-list", "--count", f"{base}..{head}"], cwd=cwd, timeout=timeout
    )
    if rc != 0:
        return 0
    if not out:
        # 边界: 空 stdout 等同"无 ahead", 避免 ``int("")`` 走 ValueError 兜底路径。
        # 旧写法 ``int(out or 0)`` 能工作但语义隐晦 (读者猜 "or 0" 是防 None?);
        # 显式早返让意图清晰。
        return 0
    try:
        return int(out)
    except ValueError:
        # 极端情况: git 输出了非数字 (e.g. "fatal: ...") 但 rc 仍 = 0? 理论上不会,
        # 但保险起见不要把 caller 弄崩
        return 0


def git_push(
    cwd: Path | str | None,
    remote: str = "origin",
    branch: str = "main",
    timeout: int | float | None = None,
) -> tuple[bool, str]:
    """``git push <remote> <branch>`` → ``(ok, msg)``。

    匹配 ``SideGit.push`` 旧契约:

      - ``ok = (rc == 0)``
      - ``msg = (stderr or stdout).strip()`` —— 没 stderr 用 stdout (git push 在
        失败时把诊断信息写到 stderr, 成功时常用 stdout)
      - 失败 (rc != 0) 时 ``ok=False`` 但 ``msg`` 必非空, 便于上层展示诊断信息

    test_sidegit.py::test_push_no_remote + test_git_tools.py::test_git_push_no_remote_returns_ok_false_with_message 锁住"无 origin 时 msg 非空"。

    Examples:
        >>> ok, msg = git_push(repo)
        >>> if not ok:
        ...     log.warning("push failed: %s", msg)
    """
    rc, out, err = run_capture(
        ["git", "push", remote, branch], cwd=cwd, timeout=timeout
    )
    return (rc == 0, (err or out).strip())


__all__ = ["git_run", "git_count_ahead", "git_push", "RC_RUNTIME_FAIL"]