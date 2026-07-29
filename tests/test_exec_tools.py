"""tests/test_exec_tools.py

覆盖 src/xragent/tools/exec_tools.py 的 4 项改动：
  1. 新参数 timeout_s（默认 30、自定义透传、非正数兜底）
  2. 公共 helper _truncate_output（bytes/str/None 三分支）
  3. 工厂函数 _fail 的返回结构稳定
  4. type hint 不会漂移 LLM 工具契约的键集合

不依赖真实 subprocess.run 的副作用：所有进程分支都用 monkeypatch
拦截，向 settings 注入一个临时 repo_root（指向 tmp_path）。
"""
from __future__ import annotations

import subprocess
from typing import Any

import pytest

from xragent.config.settings import get_settings
from xragent.tools import exec_tools


# -------------------- fixtures --------------------

@pytest.fixture
def fake_settings(tmp_path, monkeypatch):
    """把 settings.repo_root 指向 tmp_path，让 cwd 检查通过。"""
    s = get_settings()
    monkeypatch.setattr(s, "repo_root", tmp_path)
    return s


def _fake_completed(returncode: int = 0,
                    stdout: Any = "ok",
                    stderr: Any = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="x", returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# -------------------- _truncate_output --------------------

class TestTruncateOutput:
    def test_none_returns_empty(self) -> None:
        assert exec_tools._truncate_output(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert exec_tools._truncate_output("") == ""

    def test_short_str_unchanged(self) -> None:
        s = "hello"
        assert exec_tools._truncate_output(s) == s

    def test_long_str_keeps_tail(self) -> None:
        s = "x" * 5000
        out = exec_tools._truncate_output(s)
        assert len(out) == exec_tools.OUTPUT_TAIL_LIMIT
        assert out == s[-exec_tools.OUTPUT_TAIL_LIMIT:]

    def test_custom_limit(self) -> None:
        s = "abcdefghij"  # 10 chars
        assert exec_tools._truncate_output(s, limit=3) == "hij"

    def test_bytes_decoded_then_truncated(self) -> None:
        b = ("y" * 10_000).encode()
        out = exec_tools._truncate_output(b)
        assert isinstance(out, str)
        assert len(out) == exec_tools.OUTPUT_TAIL_LIMIT

    def test_bytes_with_invalid_utf8_uses_replace(self) -> None:
        # 0xff 单独是无效 utf-8 序列
        out = exec_tools._truncate_output(b"hi \xff world")
        # 必须不抛异常，且包含替换字符 U+FFFD
        assert "\ufffd" in out

    def test_exotic_type_falls_back_to_repr(self) -> None:
        out = exec_tools._truncate_output(12345)
        # repr(12345) == "12345"，刚好不会被截断
        assert "12345" in out


# -------------------- _fail --------------------

class TestFail:
    def test_minimal_shape(self) -> None:
        r = exec_tools._fail("oops")
        assert r == {"ok": False, "error": "oops"}

    def test_extra_fields_preserved(self) -> None:
        r = exec_tools._fail("timeout", timeout=True, stdout="tail", stderr="")
        assert r["ok"] is False
        assert r["error"] == "timeout"
        assert r["timeout"] is True
        assert r["stdout"] == "tail"
        assert r["stderr"] == ""

    def test_no_phantom_keys(self) -> None:
        # 锁死：除 ok/error 之外只可能出现调用方显式传入的键
        r = exec_tools._fail("x")
        assert set(r.keys()) == {"ok", "error"}


# -------------------- run_cmd: timeout_s 参数 --------------------

class TestRunCmdTimeoutS:
    def test_default_timeout_is_30(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _fake_completed(returncode=0, stdout="hi", stderr="")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        r = exec_tools.run_cmd("echo hi")
        assert r["ok"] is True
        assert captured["kwargs"]["timeout"] == exec_tools.DEFAULT_TIMEOUT_S == 30
        assert r["stdout"] == "hi"
        assert r["stderr"] == ""

    def test_custom_timeout_passed_through(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        exec_tools.run_cmd("sleep 1", timeout_s=5)
        assert captured["kwargs"]["timeout"] == 5

    def test_non_positive_timeout_falls_back_to_default(self, monkeypatch, fake_settings) -> None:
        seen: list[int] = []

        def fake_run(cmd, **kwargs):
            seen.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        for bad in (0, -1, -100):
            exec_tools.run_cmd("true", timeout_s=bad)
        assert seen == [30, 30, 30]

    def test_non_int_timeout_falls_back_to_default(self, monkeypatch, fake_settings) -> None:
        seen: list[Any] = []

        def fake_run(cmd, **kwargs):
            seen.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        # bool 是 int 的子类，但传 bool 仍要兜底；用 None 这种典型坏值
        exec_tools.run_cmd("true", timeout_s=None)  # type: ignore[arg-type]
        assert seen == [30]

    def test_cwd_is_repo_root(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true")
        assert captured["kwargs"]["cwd"] == str(fake_settings.repo_root)


# -------------------- run_cmd: 错误路径 --------------------

class TestRunCmdErrorPaths:
    def test_blacklisted_cmd_blocked_before_subprocess(self, monkeypatch, fake_settings) -> None:
        called = {"n": 0}

        def fake_run(*a, **kw):
            called["n"] += 1
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        # 找一个确认在黑名单里的命令（"rm -rf /" 是经典）
        r = exec_tools.run_cmd("rm -rf /")
        assert r["ok"] is False
        assert "命令被拦截" in r["error"]
        # 关键：subprocess 根本没被调用
        assert called["n"] == 0
        # LLM 契约：黑名单分支只暴露 ok + error，不暴露 returncode
        assert set(r.keys()) == {"ok", "error"}

    def test_timeout_returns_stable_shape(self, monkeypatch, fake_settings) -> None:
        def fake_run(*a, **kw):
            # 模拟 subprocess 的 TimeoutExpired：stdout/stderr 是 bytes
            raise subprocess.TimeoutExpired(cmd="sleep 99", timeout=2,
                                             output=b"partial-out", stderr=b"warn-err")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("sleep 99", timeout_s=2)

        assert r["ok"] is False
        assert r["timeout"] is True
        assert "超时" in r["error"]
        # 键集合稳定：ok, error, timeout, stdout, stderr
        assert set(r.keys()) == {"ok", "error", "timeout", "stdout", "stderr"}
        assert r["stdout"] == "partial-out"
        assert r["stderr"] == "warn-err"

    def test_oserror_returns_stable_shape(self, monkeypatch, fake_settings) -> None:
        def fake_run(*a, **kw):
            raise FileNotFoundError(2, "No such file or directory", "/no/shell")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("nope")
        assert r["ok"] is False
        assert r["error"].startswith("FileNotFoundError:")
        assert set(r.keys()) == {"ok", "error"}


# -------------------- type-hint 契约 --------------------

class TestTypeContract:
    """确保 type hint 的引入没有让 LLM 工具契约漂移。"""

    def test_success_keys(self, monkeypatch, fake_settings) -> None:
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout="", stderr=""),
        )
        r = exec_tools.run_cmd("true")
        assert set(r.keys()) == {"ok", "returncode", "stdout", "stderr"}
        assert isinstance(r["ok"], bool)
        assert isinstance(r["returncode"], int)
        assert isinstance(r["stdout"], str)
        assert isinstance(r["stderr"], str)

    def test_nonzero_returncode_still_ok_false(self, monkeypatch, fake_settings) -> None:
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=1, stdout="", stderr="boom"),
        )
        r = exec_tools.run_cmd("false")
        assert r["ok"] is False
        assert r["returncode"] == 1
        assert r["stderr"] == "boom"
