"""subprocess 工具：抽 main.py 和 side_git.py 的 git subprocess.run 模板。

**起因** (演化任务 "Refactor: 抽 subprocess.run git 模板"):
3 处都重复 ``subprocess.run(["git", ...], cwd=str(...), capture_output=True,
text=True, [encoding=...], [timeout=...])`` 这串 5+ 行 kwargs, 区别只在错误处理:

  - src/xragent/main.py::cmd_autonomous.maybe_periodic_push
    ``git rev-list --count``, 5s timeout, 异常吞掉 → n=0
  - src/xragent/snapshot/side_git.py::SideGit._run
    任意 git 命令, 非 0 raise ``RuntimeError``
  - src/xragent/snapshot/side_git.py::SideGit.push
    ``git push``, 返回 ``(rc==0, stderr or stdout)``

抽到 ``run_capture`` 后调用方只关心 ``(rc, out, err)`` 元组, 不再各写一遍 kwargs;
异常处理收敛到一处 (``TimeoutExpired`` / ``FileNotFoundError`` / ``OSError``
统一吞掉 → ``rc = -1``)。

**测试影响**:
tests/test_git_tools.py 用 ``monkeypatch.setattr(side_git.subprocess, "run", fake_run)``
拦截 git push 参数透传。因为 ``import subprocess`` 拿到的是模块 singleton, 而
``subprocess.run`` 在 ``run_capture`` 函数体内是动态属性查找, 所以 fake_run 在
side_git 和 subprocess_utils 里同时被看到, 现有测试不需要改。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def run_capture(
    cmd: list[str],
    cwd: "Path | str | None" = None,
    *,
    timeout: "int | float | None" = None,
    encoding: str = "utf-8",
) -> tuple[int, str, str]:
    """Run ``cmd`` 抓 stdout+stderr, 返回 ``(returncode, stdout, stderr)`` 三元组。

    Args:
        cmd: 命令列表 (e.g. ``["git", "status"]``)
        cwd: 工作目录; ``None`` = 当前进程 cwd
        timeout: 传给 ``subprocess.run`` 的超时秒数
        encoding: stdout/stderr 的文本编码 (默认 ``"utf-8"``)

    Returns:
        ``(returncode, stdout, stderr)`` — 三者都已 ``.strip()``。

    失败语义:
      - ``rc < 0`` → "运行过程本身失败" (timeout / binary 缺失 / OS error),
        ``stdout=""``, ``stderr=str(exc).strip()``
      - ``rc >= 0`` → subprocess 正常返回; 业务上的"成功/失败"由调用方按 ``rc==0`` 判断

    Examples:
        >>> rc, out, err = run_capture(["git", "rev-parse", "HEAD"], cwd="/repo")
        >>> if rc == 0:
        ...     head = out
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding=encoding,
            timeout=timeout,
        )
        return (result.returncode, result.stdout.strip(), result.stderr.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        # 吞掉统一异常: 调用方通常想要"git 失败了 → n=0 / 走 fallback", 不要裸崩
        return (-1, "", str(e).strip())