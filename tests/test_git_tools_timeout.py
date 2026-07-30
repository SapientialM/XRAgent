"""git_tools.git_push timeout 行为。

为什么独立文件: 跟 test_git_tools.py 里的\"契约锁\"分离,
这是 v0.5.4 新增 timeout_s 配套测试,只覆盖 *timeout 相关* 行为。

设计要点:
  - 用 monkeypatch 替换 ``xragent.tools.git_tools.subprocess.run``
    (git_tools 直接 import subprocess,monkeypatch 该模块的 ``subprocess``
    引用才能截到)。
  - timeout 不真等: 用 monkeypatch raise TimeoutExpired 即可,
    不引入 ``time.sleep`` 拖慢测试。
  - ``_resolve_timeout`` 是纯函数: 直接调,无 fixture。
  - ``_fail`` 工厂: 直接调,验证键集合契约。
  - 不测 registry schema: build_default_registry() 在 evolve_tools
    烂 import (pre-existing) 下挂掉;timeout 契约已由
    test_git_push_signature_exposes_timeout_s_keyword 锁住。
"""
from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest

from xragent.tools import git_tools


# ===========================================================================
# _resolve_timeout: 纯函数边界
# ===========================================================================


def test_resolve_timeout_default_used_when_none():
    """None → default(默认参数 30)。"""
    assert git_tools._resolve_timeout(None, default=30) == 30


def test_resolve_timeout_default_used_when_zero_or_negative():
    """0 / 负数 → default。0 是非法 timeout(subprocess 会立刻抛)。"""
    assert git_tools._resolve_timeout(0, default=30) == 30
    assert git_tools._resolve_timeout(-1, default=30) == 30
    assert git_tools._resolve_timeout(-0.5, default=30) == 30


def test_resolve_timeout_default_used_when_non_numeric_types():
    """str / list / dict / None.type → default。"""
    assert git_tools._resolve_timeout("30", default=30) == 30
    assert git_tools._resolve_timeout([30], default=30) == 30
    assert git_tools._resolve_timeout({"x": 30}, default=30) == 30


def test_resolve_timeout_bool_rejected_even_though_int_subclass():
    """bool 是 int 子类, 但语义不是数字 —— 必须显式拒绝,
    否则 ``True`` 会被当 ``1`` 秒timeout。
    """
    assert git_tools._resolve_timeout(True, default=30) == 30
    assert git_tools._resolve_timeout(False, default=30) == 30


def test_resolve_timeout_passes_through_positive_int_and_float():
    """合法正 int / float → int(value)。"""
    assert git_tools._resolve_timeout(60, default=30) == 60
    assert git_tools._resolve_timeout(60.7, default=30) == 60  # int() 截断
    assert git_tools._resolve_timeout(1, default=30) == 1


def test_resolve_timeout_custom_default_honored():
    """default 参数透传: 测试 / 极端场景可以临时用更短 / 更长。"""
    assert git_tools._resolve_timeout(None, default=5) == 5
    assert git_tools._resolve_timeout("x", default=120) == 120


# ===========================================================================
# _fail helper: 字典工厂契约
# ===========================================================================


def test_fail_minimum_dict_has_only_ok_and_msg():
    """无 extras 时 → ``{\"ok\": False, \"msg\": ...}``。LLM 工具契约锁。"""
    out = git_tools._fail("oops")
    assert out == {"ok": False, "msg": "oops"}
    assert set(out.keys()) == {"ok", "msg"}


def test_fail_extras_are_added_only_when_provided():
    """extras 显式传入才出现,避免 LLM 解析键集合漂移。"""
    out = git_tools._fail("oops", timed_out=True, extra="x")
    assert out == {"ok": False, "msg": "oops", "timed_out": True, "extra": "x"}


def test_fail_msg_is_positional_only():
    """msg 是 positional-only (def 里 ``msg: str, /``), 不能 kw 传。"""
    with pytest.raises(TypeError):
        git_tools._fail(msg="oops")  # type: ignore[misc]


# ===========================================================================
# git_push: timeout 透传到 subprocess.run
# ===========================================================================


def test_git_push_default_timeout_passed_to_subprocess(repo_root: Path):
    """不传 timeout_s → 默认 30s 透传给底层 subprocess.run。"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert captured["kwargs"]["timeout"] == git_tools.DEFAULT_PUSH_TIMEOUT_S == 30
    assert captured["args"] == ["git", "push", "origin", "main"]
    assert r == {"ok": True, "msg": ""}


def test_git_push_custom_timeout_passed_to_subprocess(repo_root: Path):
    """自定义 timeout_s → 透传(经过 int() 截断)。"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(timeout_s=5.9)  # float → int 截断成 5
    finally:
        monkey.undo()

    assert captured["kwargs"]["timeout"] == 5
    assert r == {"ok": True, "msg": ""}


def test_git_push_invalid_timeout_falls_back_to_default(repo_root: Path):
    """timeout_s=None / 0 / -1 / \"30\" → 仍走 30s 默认。"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        for bad in (None, 0, -1, "30", True, [30]):
            captured.clear()
            git_tools.git_push(timeout_s=bad)  # type: ignore[arg-type]
            assert captured["kwargs"]["timeout"] == 30, (
                f"timeout_s={bad!r} 应回落到默认 30, 实际={captured['kwargs']['timeout']}"
            )
    finally:
        monkey.undo()


# ===========================================================================
# git_push: 异常路径 → ok=False 字典
# ===========================================================================


def test_git_push_timeout_returns_ok_false_with_timed_out_flag(repo_root: Path):
    """subprocess.run 抛 TimeoutExpired → ``ok=False, msg=\"超时（>{t}s）\", timed_out=True``。"""
    def fake_run(args, **kwargs):
        # 与真实 subprocess 一致: TimeoutExpired 携带 timeout / cmd / output / stdout / stderr
        raise subprocess.TimeoutExpired(
            cmd=args, timeout=kwargs["timeout"],
            output=b"partial stdout", stderr=b"partial stderr",
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(timeout_s=5)
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["timed_out"] is True
    assert "5" in r["msg"]
    assert "超时" in r["msg"], f"诊断信息应含\"超时\": {r['msg']!r}"
    # 契约: msg 字符串绝对非空
    assert isinstance(r["msg"], str)
    assert r["msg"]


def test_git_push_timeout_with_default_says_30_in_message(repo_root: Path):
    """默认 timeout 触发超时 → 诊断信息明确含 \"30\"。"""
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()  # 默认 30s
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert r["timed_out"] is True
    assert "30" in r["msg"], f"默认 timeout 触发的诊断应含 \"30\": {r['msg']!r}"


def test_git_push_filenotfound_returns_ok_false_with_diag(repo_root: Path):
    """FileNotFoundError(git 二进制不存在 / cwd 不存在) → ok=False + 诊断。

    FileNotFoundError 实际是 OSError 子类; except 顺序让 FileNotFoundError
    分支先命中,诊断里写 ``FileNotFoundError: ...``。
    """
    def fake_run(args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", "/nonexistent/git")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "FileNotFoundError" in r["msg"], (
        f"诊断信息应包含异常类型名便于 LLM debug: {r['msg']!r}"
    )
    # 超时标志不应被设置(不是 TimeoutExpired)
    assert "timed_out" not in r, f"非超时异常不应带 timed_out 旗标: {r}"


def test_git_push_oserror_returns_ok_false_with_diag(repo_root: Path):
    """OSError 子类(权限 / 磁盘满 / 进程被杀) → ok=False + 诊断。

    诊断里写 ``type(e).__name__``(=子类名,如 PermissionError)而非基类
    \"OSError\",理由:子类名 + errno 解释更具体,LLM 拿到能直接用。
    """
    def fake_run(args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "PermissionError" in r["msg"], (
        f"诊断信息应包含具体子类名: {r['msg']!r}"
    )
    assert "timed_out" not in r


# ===========================================================================
# git_push: 成功路径不变 (回归保险)
# ===========================================================================


def test_git_push_success_does_not_set_timed_out_key(repo_root: Path):
    """成功 push → 返回 ``{\"ok\": True, \"msg\": \"\"}``, 不带 timed_out。"""
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r == {"ok": True, "msg": ""}
    assert "timed_out" not in r


def test_git_push_failure_rc_nonzero_still_uses_stderr(repo_root: Path):
    """returncode != 0 + 有 stderr → ``ok=False, msg=<stderr.strip()>``。

    不带 timed_out 旗标(因为走的是正常 CompletedProcess 路径)。
    """
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=128,
            stderr="fatal: repository 'origin' does not exist\n",
            stdout="",
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(git_tools.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert r["ok"] is False
    assert "fatal:" in r["msg"]
    assert "timed_out" not in r


# ===========================================================================
# 不变量: 模块级常量稳定 (防止后续重构改默认 timeout 触发回归)
# ===========================================================================


def test_default_push_timeout_constant():
    """DEFAULT_PUSH_TIMEOUT_S 必须 == 30,与 exec_tools.DEFAULT_TIMEOUT_S 对齐。"""
    from xragent.tools.exec_tools import DEFAULT_TIMEOUT_S
    assert git_tools.DEFAULT_PUSH_TIMEOUT_S == DEFAULT_TIMEOUT_S == 30


def test_git_push_signature_exposes_timeout_s_keyword():
    """inspect.signature 应暴露 timeout_s 形参,默认 = DEFAULT_PUSH_TIMEOUT_S。

    registry input_schema 也依赖这个默认值;一旦漂移,LLM 调用方拿到的
    默认值会跟实际不符。
    """
    import inspect

    sig = inspect.signature(git_tools.git_push)
    assert "timeout_s" in sig.parameters
    assert sig.parameters["timeout_s"].default == git_tools.DEFAULT_PUSH_TIMEOUT_S