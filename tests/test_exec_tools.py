"""tests/test_exec_tools.py

覆盖 src/xragent/tools/exec_tools.py 的 4 项改动:
  1. 新参数 timeout_s (默认 30、自定义透传、非正数兜底)
  2. 公共 helper _truncate_output (bytes/str/None/head+tail 四组分支)
  3. 工厂函数 _fail 的返回结构稳定
  4. type hint 不会漂移 LLM 工具契约的键集合
  5. run_cmd 透传 output_head_chars / output_tail_chars (2026-07-30 加)

不依赖真实 subprocess.run 的副作用: 所有进程分支都用 monkeypatch
拦截, 向 settings 注入一个临时 repo_root (指向 tmp_path)。
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
    """把 settings.repo_root 指向 tmp_path, 让 cwd 检查通过。"""
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
        assert exec_tools._truncate_output(s, tail_chars=3) == "hij"

    def test_bytes_decoded_then_truncated(self) -> None:
        b = ("y" * 10_000).encode()
        out = exec_tools._truncate_output(b)
        assert isinstance(out, str)
        assert len(out) == exec_tools.OUTPUT_TAIL_LIMIT

    def test_bytes_with_invalid_utf8_uses_replace(self) -> None:
        # 0xff 单独是无效 utf-8 序列
        out = exec_tools._truncate_output(b"hi \xff world")
        # 必须不抛异常, 且包含替换字符 U+FFFD
        assert "\ufffd" in out

    def test_exotic_type_falls_back_to_repr(self) -> None:
        out = exec_tools._truncate_output(12345)
        # repr(12345) == "12345", 刚好不会被截断
        assert "12345" in out



# -------------------- _coerce_int --------------------

class TestCoerceInt:
    """覆盖 _coerce_int helper 的兜底矩阵。

    设计目标: 工具 handler 入参校验应该"宽容 + 兜底", 而不是 TypeError
    冒到 LLM 面前。这里枚举所有从 LLM 端可能传过来的坏值。
    """

    def test_int_passthrough(self) -> None:
        assert exec_tools._coerce_int(5, 30) == 5
        assert exec_tools._coerce_int(1, 30) == 1

    def test_float_truncates_to_int(self) -> None:
        # 5.7 → 5; 工具层不挑舍入策略, 用 int() 的趋零截断即可
        assert exec_tools._coerce_int(5.7, 30) == 5
        assert exec_tools._coerce_int(0.9, 30) == 0  # 但会触发 min_value 兜底

    def test_bool_falls_back_to_default(self) -> None:
        # 关键: bool 是 int 子类, 必须显式拒绝 — True 会被语义化成"无限"
        # timeout, 远比一个默认值危险
        assert exec_tools._coerce_int(True, 30) == 30
        assert exec_tools._coerce_int(False, 30) == 30

    def test_none_falls_back_to_default(self) -> None:
        assert exec_tools._coerce_int(None, 30) == 30

    def test_string_falls_back_to_default(self) -> None:
        # 不解析字符串数字 — 调用方应该 int() 完再传
        assert exec_tools._coerce_int("5", 30) == 30
        assert exec_tools._coerce_int("", 30) == 30

    def test_list_dict_falls_back_to_default(self) -> None:
        assert exec_tools._coerce_int([5], 30) == 30
        assert exec_tools._coerce_int({"x": 5}, 30) == 30

    def test_below_min_value_falls_back_to_default(self) -> None:
        # min_value=1 时, 0 / 负数 / 0.9 都 fallback — 避免
        # subprocess.run(timeout=0) 立刻 ValueError
        assert exec_tools._coerce_int(0, 30, min_value=1) == 30
        assert exec_tools._coerce_int(-1, 30, min_value=1) == 30
        assert exec_tools._coerce_int(-100, 30, min_value=1) == 30

    def test_at_min_value_kept(self) -> None:
        # min_value 边界: == min_value 应该保留, 不该 fallback
        assert exec_tools._coerce_int(1, 30, min_value=1) == 1

    def test_default_min_value_is_zero(self) -> None:
        # 默认 min_value=0: 0 是合法值, head_chars=0 必须能被保留
        # (这是 _truncate_output 向后兼容的关键)
        assert exec_tools._coerce_int(0, 30) == 0

    def test_very_large_int_kept(self) -> None:
        # LLM 偶尔会脑抽传一个巨大的整数, 只要 >= min_value 就原样保留
        assert exec_tools._coerce_int(10_000_000, 30) == 10_000_000

# -------------------- _truncate_output: head + tail 双段 --------------------

class TestTruncateOutputHeadTail:
    """head_chars + tail_chars 双段保留: 截断时输出 head+省略提示+tail。"""

    def test_head_zero_backward_compatible(self) -> None:
        # head=0 等同旧行为: 只返回尾部 tail_chars
        s = "abcdefghij"  # 10 chars
        out = exec_tools._truncate_output(s, head_chars=0, tail_chars=3)
        assert out == "hij"
        assert "省略" not in out

    def test_head_tail_long_string(self) -> None:
        s = "A" * 100 + "MIDDLE" + "Z" * 100  # 206 chars
        out = exec_tools._truncate_output(s, head_chars=10, tail_chars=20)
        assert out.startswith("A" * 10)
        assert out.endswith("Z" * 20)
        assert "省略" in out
        assert "176 字" in out  # 206 - 10 - 20 = 176
        assert "MIDDLE" not in out  # 中间被砍掉

    def test_head_tail_exact_boundary_unchanged(self) -> None:
        # head + tail == len(value) → 原样返回, 不插省略提示
        s = "x" * 100
        out = exec_tools._truncate_output(s, head_chars=40, tail_chars=60)
        assert out == s
        assert "省略" not in out

    def test_head_tail_bytes(self) -> None:
        b = ("HEAD-" * 10 + "MID" * 50 + "TAIL-" * 10).encode()  # 60 + 150 + 60 = 270
        out = exec_tools._truncate_output(b, head_chars=20, tail_chars=30)
        assert isinstance(out, str)
        assert out.startswith("HEAD-HEAD-HEAD-HE")  # 20 chars
        assert out.endswith("TAIL-TAIL-TAIL-TAIL-")  # 30 chars
        assert "省略" in out

    def test_head_only_with_zero_tail(self) -> None:
        # tail_chars=0 时只保留头部, 与 head_chars=0 / tail_chars=N 对称
        s = "abcdefghij"  # 10 chars
        out = exec_tools._truncate_output(s, head_chars=3, tail_chars=0)
        # 10 > 3 + 0, 走截断分支
        assert out.startswith("abc")
        assert "省略" in out

    def test_negative_head_falls_back_to_zero(self) -> None:
        # 负数兜底: 当作 0, 行为等同 tail-only
        s = "x" * 100
        out = exec_tools._truncate_output(s, head_chars=-5, tail_chars=10)
        assert out == s[-10:]
        assert "省略" not in out

    def test_truncation_marker_is_human_readable(self) -> None:
        s = "x" * 1000
        out = exec_tools._truncate_output(s, head_chars=50, tail_chars=50)
        # 标记必须能让 LLM 一眼扫到
        assert "\n" in out  # 前后换行
        assert "..." in out
        assert "900" in out  # 省略的字数 = 1000 - 50 - 50



    def test_negative_tail_falls_back_to_default(self) -> None:
        # 负 tail_chars 兜底到 OUTPUT_TAIL_LIMIT
        long_s = "x" * 10_000
        out = exec_tools._truncate_output(long_s, head_chars=0, tail_chars=-5)
        assert len(out) == exec_tools.OUTPUT_TAIL_LIMIT

    def test_string_tail_falls_back_to_default(self) -> None:
        # 字符串 tail_chars 兜底, 不会试图"100 字"这样
        long_s = "x" * 10_000
        out = exec_tools._truncate_output(long_s, head_chars=0, tail_chars="oops")  # type: ignore[arg-type]
        assert len(out) == exec_tools.OUTPUT_TAIL_LIMIT

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
        # 锁死: 除 ok/error 之外只可能出现调用方显式传入的键
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

        # bool 是 int 的子类, 但传 bool 仍要兜底; 用 None 这种典型坏值
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



    def test_bool_timeout_falls_back_to_default(self, monkeypatch, fake_settings) -> None:
        # 单独拎出来: bool 是 int 子类, _coerce_int 必须显式拒绝
        seen: list[int] = []

        def fake_run(cmd, **kwargs):
            seen.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true", timeout_s=True)  # type: ignore[arg-type]
        assert seen == [30]

# -------------------- run_cmd: output_head_chars / output_tail_chars 透传 --------------------

class TestRunCmdOutputTruncation:
    """2026-07-30 新增: run_cmd 把 head/tail 透传给 _truncate_output。

    重点验证三个调用位点 (成功 / 超时 / OSError) 都用同一对参数,
    且默认行为不变。
    """

    def test_default_head_is_zero_keeps_old_contract(self, monkeypatch, fake_settings) -> None:
        long_out = "X" * 5000
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout=long_out, stderr=""),
        )
        r = exec_tools.run_cmd("echo")
        # 默认 head=0 + tail=4000, 与旧版完全一致
        assert len(r["stdout"]) == exec_tools.OUTPUT_TAIL_LIMIT == 4000
        assert r["stdout"] == long_out[-4000:]
        assert "省略" not in r["stdout"]

    def test_head_chars_truncates_success_stdout(self, monkeypatch, fake_settings) -> None:
        long_out = "HEAD-" * 20 + "MID-" * 200 + "TAIL-" * 20  # 100 + 600 + 100 = 800
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout=long_out, stderr=""),
        )
        r = exec_tools.run_cmd("echo", output_head_chars=50, output_tail_chars=80)
        assert r["stdout"].startswith("HEAD-" * 10)  # 50 chars
        assert r["stdout"].endswith("TAIL-" * 16)    # 80 chars
        assert "省略" in r["stdout"]
        assert "MID-" not in r["stdout"]
        # 键集合稳定
        assert set(r.keys()) == {"ok", "returncode", "stdout", "stderr"}

    def test_head_chars_truncates_success_stderr(self, monkeypatch, fake_settings) -> None:
        long_err = "E" * 800
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout="", stderr=long_err),
        )
        r = exec_tools.run_cmd("echo", output_head_chars=20, output_tail_chars=30)
        assert r["stderr"].startswith("E" * 20)
        assert r["stderr"].endswith("E" * 30)
        assert "省略" in r["stderr"]

    def test_head_chars_applies_to_timeout_branch(self, monkeypatch, fake_settings) -> None:
        def fake_run(*a, **kw):
            raise subprocess.TimeoutExpired(
                cmd="sleep 99", timeout=2,
                output=b"HEAD-OUTPUT-" * 50 + b"MID" * 100 + b"-TAIL-OUTPUT" * 50,
                stderr=b"E" * 800,
            )
        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd(
            "sleep 99", timeout_s=2,
            output_head_chars=20, output_tail_chars=30,
        )
        assert r["ok"] is False
        assert r["timeout"] is True
        # stdout/stderr 都走了 head+tail 截断
        assert r["stdout"].startswith("HEAD-OUTPUT-HEAD")  # 20 chars
        assert r["stdout"].endswith("OUTPUT-TAIL-OUTPUT-TAIL-OUTPUT")  # 30 chars
        assert "省略" in r["stdout"]
        assert r["stderr"].startswith("E" * 20)
        assert "省略" in r["stderr"]

    def test_head_chars_zero_with_long_output(self, monkeypatch, fake_settings) -> None:
        # 显式传 head=0 (与默认等价), 验证旧契约稳定
        s = "x" * 5000
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout=s, stderr=""),
        )
        r = exec_tools.run_cmd("echo", output_head_chars=0, output_tail_chars=100)
        assert r["stdout"] == s[-100:]
        assert "省略" not in r["stdout"]

    def test_short_output_unchanged_with_head_chars(self, monkeypatch, fake_settings) -> None:
        short = "hello world"
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout=short, stderr=short),
        )
        r = exec_tools.run_cmd("echo", output_head_chars=20, output_tail_chars=20)
        assert r["stdout"] == short
        assert r["stderr"] == short
        assert "省略" not in r["stdout"]

    def test_keyset_unchanged_when_head_chars_set(self, monkeypatch, fake_settings) -> None:
        # 关键: 加新参数不能引入新键 (LLM 契约稳定)
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout="ok", stderr=""),
        )
        r = exec_tools.run_cmd("true", output_head_chars=100, output_tail_chars=100)
        assert set(r.keys()) == {"ok", "returncode", "stdout", "stderr"}


# -------------------- run_cmd: 错误路径 --------------------

class TestRunCmdErrorPaths:
    def test_blacklisted_cmd_blocked_before_subprocess(self, monkeypatch, fake_settings) -> None:
        called = {"n": 0}

        def fake_run(*a, **kw):
            called["n"] += 1
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

        # 找一个确认在黑名单里的命令 ("rm -rf /" 是经典)
        r = exec_tools.run_cmd("rm -rf /")
        assert r["ok"] is False
        assert "命令被拦截" in r["error"]
        # 关键: subprocess 根本没被调用
        assert called["n"] == 0
        # LLM 契约: 黑名单分支只暴露 ok + error, 不暴露 returncode
        assert set(r.keys()) == {"ok", "error"}

    def test_timeout_returns_stable_shape(self, monkeypatch, fake_settings) -> None:
        def fake_run(*a, **kw):
            # 模拟 subprocess 的 TimeoutExpired: stdout/stderr 是 bytes
            raise subprocess.TimeoutExpired(cmd="sleep 99", timeout=2,
                                             output=b"partial-out", stderr=b"warn-err")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("sleep 99", timeout_s=2)

        assert r["ok"] is False
        assert r["timeout"] is True
        assert "超时" in r["error"]
        # 键集合稳定: ok, error, timeout, stdout, stderr
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
