"""git_tools._run_subprocess_git helper + git_push 端到端兜底契约（v0.5.7）。

为什么独立文件: 与 ``test_git_tools_timeout.py`` 分离。前者锁
git_push **业务契约** (timeout_s 透传 / OK bool + msg str / timed_out
旗标), 本文件锁 **helper 抽象层 + generic Exception 兜底** —— 这是
v0.5.7 的核心新行为。

覆盖矩阵:

  _run_subprocess_git 直接调用 (helper 单元)
    - 成功 (rc=0): ``{ok: True, msg: ""}``
    - 成功 (rc!=0): ``{ok: False, msg: stderr.strip()}``
    - TimeoutExpired: ``{ok: False, msg: "超时（>{t}s）", timed_out: True}``
    - FileNotFoundError: ``{ok: False, msg: 含 "FileNotFoundError"}``
    - OSError 子类 (PermissionError): ``{ok: False, msg: 含 "PermissionError"}``
    - 通用 Exception (ValueError): ``{ok: False, msg: 含 "ValueError"}`` ← v0.5.7 新增
    - 返回值类型契约: ok 是 bool, msg 是 str
    - 通用 Exception 路径**不**带 timed_out 旗标 (只有 TimeoutExpired 带)

  git_push 端到端 (helper 集成 + 业务契约)
    - subprocess.run 抛 ValueError → git_push 返回 ok=False, msg 含诊断, **不冒泡**
    - 默认行为不变 (透传 remote/branch/timeout_s 到 helper)

设计要点:
  - monkeypatch ``xragent.tools.git_tools.subprocess.run`` (与
    test_git_tools_timeout.py 同样的截点)
  - helper 直接调无需 fixture (纯函数)
  - 不真等 timeout: raise 即可
  - 不测 registry schema: timeout 契约由 test_git_tools_timeout.py 锁
"""
from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest

from xragent.tools import git_tools


# ===========================================================================
# _run_subprocess_git: 成功路径
# ===========================================================================


def test_run_subprocess_git_success_rc_zero_returns_ok_true(repo_root: Path):
    """rc == 0 + stderr/stdout 都空 → ``{ok: True, msg: ""}``。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "status"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r == {"ok": True, "msg": ""}
    assert "timed_out" not in r  # 成功路径绝对不带 timed_out 旗标


def test_run_subprocess_git_success_with_stderr_uses_stderr(repo_root: Path):
    """rc != 0 + 有 stderr → ``{ok: False, msg: stderr.strip()}``。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128,
            stderr="fatal: not a git repository\n",
            stdout="some stdout we should ignore",
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "status"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "fatal:" in r["msg"]
    assert "not a git repository" in r["msg"]
    # stdout 不应进入 msg (stderr 优先)
    assert "some stdout" not in r["msg"]
    assert "timed_out" not in r


def test_run_subprocess_git_success_falls_back_to_stdout_when_stderr_empty(
    repo_root: Path,
):
    """rc != 0 但 stderr 为空 → msg 取 stdout.strip()。

    极少数 git 子命令会把错误信息打到 stdout (例如 ``git`` 在某些
    locale 下)。这条锁住 fallback 语义, 避免后续重构悄悄丢掉诊断。
    """
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1,
            stderr="",
            stdout="warning: nothing to commit\n",
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "commit"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "nothing to commit" in r["msg"]
    assert "timed_out" not in r


# ===========================================================================
# _run_subprocess_git: TimeoutExpired 路径 (与 git_push 业务契约对齐)
# ===========================================================================


def test_run_subprocess_git_timeout_returns_timed_out_flag(repo_root: Path):
    """subprocess.run 抛 TimeoutExpired → ``timed_out=True`` + 超时秒数入 msg。"""
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "fetch"], cwd=str(repo_root), timeout_s=7,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["timed_out"] is True
    assert "7" in r["msg"]
    assert "超时" in r["msg"]


# ===========================================================================
# _run_subprocess_git: 文件 / IO 类异常
# ===========================================================================


def test_run_subprocess_git_filenotfound_returns_class_name_in_msg(repo_root: Path):
    """FileNotFoundError (git 二进制不存在 / cwd 不存在) → 类名入 msg。

    FileNotFoundError 是 OSError 子类; except 顺序让 FileNotFoundError
    分支先命中, 诊断里写 ``FileNotFoundError: ...``。
    """
    def fake_run(args, **kwargs):
        raise FileNotFoundError(
            errno.ENOENT, "No such file or directory", "/nonexistent/git"
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "push"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "FileNotFoundError" in r["msg"]
    # 超时旗标不应被设置 (不是 TimeoutExpired)
    assert "timed_out" not in r


def test_run_subprocess_git_oserror_subclass_returns_subclass_name(repo_root: Path):
    """OSError 子类 (PermissionError / DiskFull 等) → 用子类名诊断。

    ``type(e).__name__`` 优先取子类名 (PermissionError 而非 OSError),
    便于 LLM 拿到 errno 对应的具体诊断信息。
    """
    def fake_run(args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "push"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "PermissionError" in r["msg"]  # 子类名
    assert "timed_out" not in r


# ===========================================================================
# _run_subprocess_git: 通用 Exception 兜底 (v0.5.7 新增行为)
# ===========================================================================


def test_run_subprocess_git_generic_exception_value_error_caught(repo_root: Path):
    """subprocess.run 抛 ValueError (非 OSError / 非 TimeoutExpired) → 兜底转 dict。

    这是 v0.5.7 的核心新增行为 —— 之前 git_push 没有这层 except,
    ValueError 会一路冒泡到 LLM 工具调用方。helper 现在三层 except,
    把所有 Exception 子类都吃掉转 ``_fail("<type>: <e>")`` dict。
    """
    def fake_run(args, **kwargs):
        raise ValueError("invalid git ref name")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "push"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "ValueError" in r["msg"]
    assert "invalid git ref name" in r["msg"]
    # 关键: 不应带 timed_out 旗标 (只有 TimeoutExpired 才带)
    assert "timed_out" not in r


def test_run_subprocess_git_generic_exception_runtime_error_caught(repo_root: Path):
    """subprocess.run 抛 RuntimeError → 兜底转 dict。

    RuntimeError 是 git_helpers.git_run 在 rc != 0 时实际抛出的类型;
    之前可能绕过 git_push 的 except (FileNotFoundError, OSError) 直接冒泡,
    现在被 helper 的 except Exception 兜住。
    """
    def fake_run(args, **kwargs):
        raise RuntimeError("git rev-parse failed: ambiguous argument")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools._run_subprocess_git(
            ["git", "push"], cwd=str(repo_root), timeout_s=10,
        )
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "RuntimeError" in r["msg"]
    assert "ambiguous argument" in r["msg"]
    assert "timed_out" not in r


def test_run_subprocess_git_does_not_swallow_keyboard_interrupt(repo_root: Path):
    """``KeyboardInterrupt`` / ``SystemExit`` 是 BaseException 而非 Exception 子类,
    **不应**被 helper 兜住 —— LLM 中断 / supervisor 重启行为不能丢。

    这条锁的是 except 子句的精确边界 (只吃 Exception, 不吃 BaseException)。
    """
    def fake_run(args, **kwargs):
        raise KeyboardInterrupt("user pressed Ctrl-C")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        with pytest.raises(KeyboardInterrupt):
            git_tools._run_subprocess_git(
                ["git", "push"], cwd=str(repo_root), timeout_s=10,
            )
    finally:
        monkey.undo()


# ===========================================================================
# _run_subprocess_git: 返回值类型契约 (LLM 解析契约)
# ===========================================================================


def test_run_subprocess_git_ok_always_bool(repo_root: Path):
    """返回值 ``ok`` 字段恒为 bool —— 任何路径 (成功 / 失败 / 异常兜底) 都是 bool。

    LLM 解析契约的一部分: ``r["ok"] is True / is False`` 不能是 truthy / falsy
    的其他类型 (int / None / str)。
    """
    # 1) 成功路径
    def fake_run_ok(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run_ok)
    try:
        r = git_tools._run_subprocess_git(["git", "status"], cwd=str(repo_root), timeout_s=10)
        assert type(r["ok"]) is bool, f"ok 应是 bool, 实际 {type(r['ok'])}"

        # 2) 失败 (rc != 0)
        def fake_run_fail(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args, returncode=1, stderr="err\n", stdout="",
            )
        monkey.setattr(git_tools.subprocess, "run", fake_run_fail)
        r = git_tools._run_subprocess_git(["git", "status"], cwd=str(repo_root), timeout_s=10)
        assert type(r["ok"]) is bool

        # 3) 异常兜底
        def fake_run_boom(args, **kwargs):
            raise ValueError("x")
        monkey.setattr(git_tools.subprocess, "run", fake_run_boom)
        r = git_tools._run_subprocess_git(["git", "status"], cwd=str(repo_root), timeout_s=10)
        assert type(r["ok"]) is bool
    finally:
        monkey.undo()


def test_run_subprocess_git_msg_always_str(repo_root: Path):
    """返回值 ``msg`` 字段恒为 str —— 失败时非空, 成功时空。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        # 成功 → 空 str (不是 None)
        r = git_tools._run_subprocess_git(["git", "status"], cwd=str(repo_root), timeout_s=10)
        assert type(r["msg"]) is str
        assert r["msg"] == ""

        # 失败 → 非空 str
        def fake_run_fail(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args, returncode=1, stderr="boom\n", stdout="",
            )
        monkey.setattr(git_tools.subprocess, "run", fake_run_fail)
        r = git_tools._run_subprocess_git(["git", "status"], cwd=str(repo_root), timeout_s=10)
        assert type(r["msg"]) is str
        assert r["msg"]  # 非空
    finally:
        monkey.undo()


# ===========================================================================
# _run_subprocess_git: args / cwd / timeout_s 透传到 subprocess.run
# ===========================================================================


def test_run_subprocess_git_passes_args_cwd_timeout_to_subprocess(repo_root: Path):
    """helper 必须把 args / cwd / timeout_s 完整透传给 subprocess.run。"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        git_tools._run_subprocess_git(
            ["git", "rev-parse", "HEAD"],
            cwd="/custom/cwd",
            timeout_s=42,
        )
    finally:
        monkey.undo()

    assert captured["args"] == ["git", "rev-parse", "HEAD"]
    assert captured["kwargs"]["cwd"] == "/custom/cwd"
    assert captured["kwargs"]["timeout"] == 42
    # capture_output=True / text=True 必须设, 跟 git_push 旧版一致
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


# ===========================================================================
# git_push: 端到端 generic Exception 兜底 (v0.5.7 新契约)
# ===========================================================================


def test_git_push_generic_exception_does_not_propagate(repo_root: Path):
    """subprocess.run 抛 ValueError (非 OSError / 非 TimeoutExpired) →
    git_push 返回 dict, **绝不冒泡异常**。

    这是 v0.5.7 修复的契约漏洞 —— 之前 git_push 只有 except
    (FileNotFoundError, OSError), ValueError / RuntimeError / 其他
    Exception 会一路冒泡到 LLM 工具调用方把 ReAct 循环打挂。现在
    helper 的 ``except Exception`` 兜底, git_push 透传到 helper。
    """
    def fake_run(args, **kwargs):
        raise ValueError("unexpected subprocess failure")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "ValueError" in r["msg"]
    assert "unexpected subprocess failure" in r["msg"]
    assert "timed_out" not in r


def test_git_push_generic_exception_preserves_remote_branch_timeout(repo_root: Path):
    """generic Exception 兜底时, git_push 仍把 remote/branch/timeout_s 透传下去。

    用 captured args/kwargs 验证 helper 收到的输入与 git_push 的输入一致。
    """
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise RuntimeError("git rev-parse HEAD failed")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(remote="upstream", branch="dev", timeout_s=15)
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "RuntimeError" in r["msg"]
    # args 应包含 push + remote + branch
    assert captured["args"] == ["git", "push", "upstream", "dev"]
    # timeout_s 必须透传
    assert captured["kwargs"]["timeout"] == 15
    assert "timed_out" not in r


def test_git_push_timeout_via_helper_unaffected(repo_root: Path):
    """helper 新增 except Exception **不破坏** TimeoutExpired 路径。

    TimeoutExpired 在 except 链中独立分支, 通用 Exception 必须保留
    timed_out 旗标语义, 不能吞成 ``ok=False msg="..." timed_out=False``。
    """
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(timeout_s=8)
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["timed_out"] is True
    assert "8" in r["msg"]


# ===========================================================================
# 测试夹具
# ===========================================================================


@pytest.fixture
def repo_root(tmp_path) -> Path:
    """返回临时目录作为 cwd —— helper 本身不要求 cwd 是 git 仓库。"""
    return tmp_path
