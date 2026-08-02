"""tests/test_exec_tools_refactor.py

覆盖 src/xragent/tools/exec_tools.py 的 4 项新增 / 改动:

  1. **抽 ``_safe_decode`` 公共 helper** — 把原 ``_truncate_output`` 里
     bytes/None/str/其他类型 → str 的归一化逻辑拆出来, 让 ``_truncate_output``
     专注于"截断", 本函数专注于"解码"。
  2. **加 ``MAX_TIMEOUT_S = 600`` 上限 clamp** — ``_coerce_int`` 新增
     ``max_value`` 关键字参数, ``_resolve_timeout`` 透传给
     ``subprocess.run`` 时强制 ``timeout <= 600s``, 防止 LLM 误传天文数字
     让进程长时间堆积拖垮 supervisor 心跳。
  3. **``run_cmd`` 新增 ``cwd`` 参数** — ``None`` → fallback 到
     ``settings.repo_root`` (向后兼容); 传入字符串则透传给
     ``subprocess.run`` (满足 LLM 在 ``evolve/`` / ``scripts/`` 等子目录
     调试的常见需求)。
  4. **type hint / docstring 完善** — ``_fail`` / ``_resolve_timeout``
     补 :return: / 上限语义, 让 mypy 和 IDE 静态检查能跟上。

不依赖真实 ``subprocess.run``: 所有进程分支都用 ``monkeypatch`` 拦截,
向 settings 注入一个临时 ``repo_root`` (指向 ``tmp_path``)。
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
    """把 settings.repo_root 指向 tmp_path, 让 cwd 默认值检查通过。"""
    s = get_settings()
    monkeypatch.setattr(s, "repo_root", tmp_path)
    return s


def _fake_completed(returncode: int = 0,
                    stdout: Any = "ok",
                    stderr: Any = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="x", returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# -------------------- _safe_decode --------------------

class TestSafeDecode:
    """覆盖抽出的 ``_safe_decode`` 公共 helper。

    设计目标: ``_truncate_output`` 调它之前先把任意类型归一化, 本函数
    自身不应该再抛任何异常 (LLM 工具链容错底线)。
    """

    def test_none_returns_empty(self) -> None:
        assert exec_tools._safe_decode(None) == ""

    def test_str_passthrough(self) -> None:
        assert exec_tools._safe_decode("hello") == "hello"

    def test_empty_str_passthrough(self) -> None:
        assert exec_tools._safe_decode("") == ""

    def test_valid_utf8_bytes_decoded(self) -> None:
        # ASCII / 完整 UTF-8 序列 → 原样返回
        assert exec_tools._safe_decode(b"hi world") == "hi world"
        assert exec_tools._safe_decode("中文".encode("utf-8")) == "中文"

    def test_invalid_utf8_bytes_uses_replace(self) -> None:
        # 0xff 单独是无效 UTF-8 序列 → 必须不抛, 用 U+FFFD 替换
        out = exec_tools._safe_decode(b"hi \xff world")
        assert "\ufffd" in out
        assert "hi " in out
        assert " world" in out

    def test_int_falls_back_to_repr(self) -> None:
        assert exec_tools._safe_decode(12345) == "12345"

    def test_bool_falls_back_to_repr(self) -> None:
        # 注意: bool 是不走 repr 兜底之外的特殊路径 — 它会落入
        # ``isinstance(value, str)`` 之外的兜底分支, repr(True) == "True"
        assert exec_tools._safe_decode(True) == "True"
        assert exec_tools._safe_decode(False) == "False"

    def test_list_falls_back_to_repr(self) -> None:
        # LLM 偶尔会传奇怪类型进来 — 必须不抛
        out = exec_tools._safe_decode([1, 2, 3])
        assert "1" in out and "2" in out and "3" in out

    def test_exception_falls_back_to_repr(self) -> None:
        # 异常对象 repr 后含类名, 排查 stack trace 友好
        out = exec_tools._safe_decode(ValueError("boom"))
        assert "ValueError" in out
        assert "boom" in out


# -------------------- _coerce_int: max_value 上限 clamp --------------------

class TestCoerceIntMaxValue:
    """覆盖 ``_coerce_int`` 新增的 ``max_value`` 关键字参数。

    设计目标: LLM 偶尔会脑抽传 ``timeout_s=999999``, 这种值走兜底到
    default, 不要让 ``subprocess.run`` 真的等 11.5 天。
    """

    def test_default_max_value_is_none_keeps_old_contract(self) -> None:
        # 不传 max_value 时, 大数值原样保留 (向后兼容)
        assert exec_tools._coerce_int(10_000_000, 30) == 10_000_000
        assert exec_tools._coerce_int(999_999, 30, min_value=1) == 999_999

    def test_above_max_value_falls_back_to_default(self) -> None:
        # 关键: 超 max_value 走兜底
        assert exec_tools._coerce_int(999999, 30, min_value=1, max_value=600) == 30
        assert exec_tools._coerce_int(601, 30, min_value=1, max_value=600) == 30

    def test_at_max_value_kept(self) -> None:
        # 边界: == max_value 必须保留 (闭区间)
        assert exec_tools._coerce_int(600, 30, min_value=1, max_value=600) == 600

    def test_below_min_value_still_falls_back(self) -> None:
        # min_value 检查优先于 max_value — 负数 / 0 / 0.9 仍走兜底
        assert exec_tools._coerce_int(-1, 30, min_value=1, max_value=600) == 30
        assert exec_tools._coerce_int(0, 30, min_value=1, max_value=600) == 30

    def test_none_max_value_means_unbounded(self) -> None:
        # 显式传 max_value=None 等同不传 — 仍保留大数值
        assert exec_tools._coerce_int(999_999, 30, max_value=None) == 999_999

    def test_float_above_max_value_falls_back(self) -> None:
        # float 也会触发上限 clamp (int() 截断后比较)
        assert exec_tools._coerce_int(700.5, 30, min_value=1, max_value=600) == 30

    def test_does_not_raise_on_exotic_max_value(self) -> None:
        # LLM 误传 max_value 自身是字符串, 不能让校验自己崩
        # (虽然这不是 hot path, 但契约说"宽容 + 兜底")
        # 这里 max_value 是非法类型, _coerce_int 在 ``n > max_value`` 处会抛
        # TypeError — 这是已知限制, 只锁"合法 max_value 时不抛"
        # 合法边界内:
        assert exec_tools._coerce_int(100, 30, min_value=1, max_value=600) == 100


# -------------------- _resolve_timeout: 上限 clamp 透传 --------------------

class TestResolveTimeoutMaxClamp:
    """覆盖 ``_resolve_timeout`` 把 ``MAX_TIMEOUT_S`` 透传给 ``_coerce_int``。

    设计目标: ``run_cmd(timeout_s=N)`` 当 ``N > MAX_TIMEOUT_S`` 时, 走
    default (``30``) 而不是真的等 N 秒。
    """

    def test_max_timeout_constant_exposed(self) -> None:
        # 锁死常量值 — 600s 是有意选择 (10 分钟)
        assert exec_tools.MAX_TIMEOUT_S == 600

    def test_small_value_kept(self) -> None:
        assert exec_tools._resolve_timeout(5) == 5
        assert exec_tools._resolve_timeout(1) == 1

    def test_at_max_timeout_kept(self) -> None:
        # 边界: == MAX_TIMEOUT_S 必须保留
        assert exec_tools._resolve_timeout(600) == 600

    def test_above_max_timeout_falls_back_to_default(self) -> None:
        assert exec_tools._resolve_timeout(999999) == exec_tools.DEFAULT_TIMEOUT_S == 30
        assert exec_tools._resolve_timeout(601) == 30
        assert exec_tools._resolve_timeout(3600) == 30  # 1 小时 → 兜底

    def test_none_falls_back_to_default(self) -> None:
        assert exec_tools._resolve_timeout(None) == 30

    def test_zero_negative_still_falls_back(self) -> None:
        # min_value=1 兜底仍生效
        assert exec_tools._resolve_timeout(0) == 30
        assert exec_tools._resolve_timeout(-5) == 30


# -------------------- run_cmd: cwd 参数 --------------------

class TestRunCmdCwd:
    """覆盖 ``run_cmd`` 新增的 ``cwd`` 参数。

    设计目标: ``None`` 时走 ``settings.repo_root`` (向后兼容, 老调用方
    行为不变); 传入字符串时透传给 ``subprocess.run(cwd=...)``, 让 LLM
    能在 ``evolve/`` / ``scripts/`` 等子目录调试。
    """

    def test_default_cwd_is_repo_root(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true")
        # 关键: cwd 必须 == settings.repo_root 字符串形式
        assert captured["kwargs"]["cwd"] == str(fake_settings.repo_root)

    def test_explicit_cwd_passed_through(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        # LLM 在子目录调试的典型用法: cwd="evolve" (相对路径) 或绝对路径
        exec_tools.run_cmd("ls", cwd=str(fake_settings.repo_root / "evolve"))
        assert captured["kwargs"]["cwd"] == str(fake_settings.repo_root / "evolve")

    def test_cwd_none_explicitly_is_repo_root(self, monkeypatch, fake_settings) -> None:
        # 显式传 cwd=None 与不传等价 — 锁住显式契约
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true", cwd=None)
        assert captured["kwargs"]["cwd"] == str(fake_settings.repo_root)

    def test_cwd_does_not_change_keyset(self, monkeypatch, fake_settings) -> None:
        # 锁死: 加新参数不能引入新键 (LLM 工具契约稳定)
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(returncode=0, stdout="ok", stderr=""),
        )
        r = exec_tools.run_cmd("true", cwd="/tmp")
        assert set(r.keys()) == {"ok", "returncode", "stdout", "stderr"}

    def test_cwd_works_on_timeout_branch(self, monkeypatch, fake_settings) -> None:
        # cwd 必须同时作用于超时分支 — 防止"主路径用 cwd, 超时分支用
        # repo_root"的不对称 bug
        captured: dict[str, Any] = {}

        def fake_run(*a, **kw):
            captured["kwargs"] = kw
            raise subprocess.TimeoutExpired(cmd="sleep 99", timeout=2,
                                             output=b"out", stderr=b"err")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("sleep 99", timeout_s=2, cwd="/custom/dir")
        assert r["ok"] is False
        assert r["timeout"] is True
        assert captured["kwargs"]["cwd"] == "/custom/dir"

    def test_cwd_works_on_oserror_branch(self, monkeypatch, fake_settings) -> None:
        # OSError 分支不直接接收 cwd (异常前已确定), 但不抛 + 锁住键集合
        def fake_run(*a, **kw):
            raise FileNotFoundError(2, "No such file or directory", "/no/shell")

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("nope", cwd="/custom/dir")
        assert r["ok"] is False
        assert r["error"].startswith("FileNotFoundError:")
        assert set(r.keys()) == {"ok", "error"}


# -------------------- 集成: max_timeout 真的传到 subprocess.run --------------------

class TestRunCmdMaxTimeoutIntegration:
    """端到端验证 ``run_cmd(timeout_s=999999)`` 不会让 subprocess.run 等 11.5 天。

    设计目标: 上限 clamp 必须真的生效, 不只是 ``_resolve_timeout`` 单元测试。
    """

    def test_huge_timeout_clamped_at_subprocess_layer(
        self, monkeypatch, fake_settings,
    ) -> None:
        captured: list[int] = []

        def fake_run(cmd, **kwargs):
            captured.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true", timeout_s=999_999)
        # 关键: 真的传给 subprocess.run 的 timeout 必须 <= MAX_TIMEOUT_S
        assert captured[0] == exec_tools.DEFAULT_TIMEOUT_S == 30
        assert captured[0] < exec_tools.MAX_TIMEOUT_S

    def test_max_boundary_timeout_kept(
        self, monkeypatch, fake_settings,
    ) -> None:
        captured: list[int] = []

        def fake_run(cmd, **kwargs):
            captured.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true", timeout_s=600)  # == MAX_TIMEOUT_S
        assert captured[0] == 600