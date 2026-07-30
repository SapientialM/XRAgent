"""tests/test_exec_tools_refactor.py

5.3 改进：给 run_cmd 加 cwd（仓库内围栏）+ env（透传）两个新参数。

设计动机：
  * LLM 经常需要 ``cd tests/ && pytest -q``、``cd src && python -m foo`` 这种
    命令；之前只能走 ``(cd X && cmd)``，多了一层 shell 嵌套，错误信息也容易
    被吞。
  * LLM 经常需要往子进程注入 ``API_KEY`` / ``HTTPS_PROXY`` 等环境变量；
    之前只能 ``KEY=val cmd``，含敏感字符 (空格 / $ / ;) 时要么写错，要么
    只能走 ``shlex.quote``。

设计约束（与 5.2 一致）：
  * cwd 必须仍位于 settings.repo_root 之内（走 PathSandbox.assert_inside），
    防止 LLM 跳到 /etc /tmp 之类"工具黑名单覆盖不到"的目录。
  * env 只做透传，不做键名 allowlist —— 由调用方/LLM 自行负责，subprocess
    默认会把当前 os.environ 与传入 env 合并（传入键覆盖）。

锁定的契约（必须保留向后兼容）：
  * ``cmd`` 仍必填、positional。
  * ``timeout_s`` 行为不变（None / 非正数 / 非数值 → 30s）。
  * 成功 / 失败 / 超时 / 黑名单 / OSError 五条返回键集合与 5.2 保持一致。
  * ``cwd`` 越界返回 ``{"ok": False, "error": "..."}``，与黑名单拦截形态一致
    （不暴露"返回码/stdout"，避免 LLM 把越界当成普通失败重试）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from xragent.config.settings import get_settings
from xragent.tools import exec_tools


# -------------------- fixtures --------------------

@pytest.fixture
def fake_settings(tmp_path, monkeypatch):
    """把 settings.repo_root 指向 tmp_path，让 PathSandbox 围栏校验通过。"""
    s = get_settings()
    monkeypatch.setattr(s, "repo_root", tmp_path)
    return s


def _fake_completed(returncode: int = 0,
                    stdout: Any = "ok",
                    stderr: Any = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="x", returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# -------------------- _resolve_cwd helper --------------------

class TestResolveCwd:
    """_resolve_cwd 是新增的 helper；现在直接暴露给测试，确保围栏逻辑不退化。"""

    def test_none_returns_repo_root(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        resolved, err = exec_tools._resolve_cwd(None, sandbox)
        assert err is None
        assert resolved == tmp_path

    def test_empty_string_returns_repo_root(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        resolved, err = exec_tools._resolve_cwd("", sandbox)
        assert err is None
        assert resolved == tmp_path

    def test_relative_subdir_resolves_inside_repo(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        # 子目录 sandbox/ 由 conftest 建好
        resolved, err = exec_tools._resolve_cwd("sandbox", sandbox)
        assert err is None
        assert resolved == (tmp_path / "sandbox").resolve()

    def test_absolute_inside_repo(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        target = (tmp_path / "diary" / "turns").resolve()
        resolved, err = exec_tools._resolve_cwd(str(target), sandbox)
        assert err is None
        assert resolved == target

    def test_outside_repo_blocked(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        # /etc 是经典"跳出去"目标；mac 上可能不存在，但 sandbox 拒它不依赖
        # 路径存在性 —— resolve() 走的是纯 lexical。
        resolved, err = exec_tools._resolve_cwd("/etc", sandbox)
        assert resolved is None
        assert err is not None
        assert "目标越界" in err["error"]
        assert set(err.keys()) == {"ok", "error"}

    def test_parent_traversal_blocked(self, fake_settings, tmp_path) -> None:
        from xragent.tools.blacklist import PathSandbox
        sandbox = PathSandbox(root=tmp_path)
        # ../ 试图跳到仓库根的父目录
        resolved, err = exec_tools._resolve_cwd("../", sandbox)
        assert resolved is None
        assert err is not None
        assert "目标越界" in err["error"]


# -------------------- run_cmd: cwd 参数 --------------------

class TestRunCmdCwd:
    def test_default_cwd_is_repo_root(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true")
        assert captured["kwargs"]["cwd"] == str(fake_settings.repo_root)

    def test_cwd_passed_through_when_inside_repo(self, monkeypatch, fake_settings, tmp_path) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        sub = tmp_path / "sandbox"
        r = exec_tools.run_cmd("ls", cwd=str(sub))
        assert r["ok"] is True
        assert captured["kwargs"]["cwd"] == str(sub.resolve())

    def test_relative_cwd_resolves_against_repo_root(self, monkeypatch, fake_settings, tmp_path) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("pytest -q", cwd="sandbox")
        assert r["ok"] is True
        assert captured["kwargs"]["cwd"] == str((tmp_path / "sandbox").resolve())

    def test_cwd_outside_repo_blocks_before_subprocess(self, monkeypatch, fake_settings) -> None:
        called = {"n": 0}

        def fake_run(*a, **kw):
            called["n"] += 1
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("ls", cwd="/etc")
        assert r["ok"] is False
        assert "目标越界" in r["error"]
        # 关键：subprocess 根本没被调用 —— 围栏提前拦截
        assert called["n"] == 0
        # LLM 契约：越界只暴露 ok + error，不暴露 returncode / stdout
        assert set(r.keys()) == {"ok", "error"}

    def test_cwd_parent_traversal_blocks_before_subprocess(self, monkeypatch, fake_settings) -> None:
        called = {"n": 0}

        def fake_run(*a, **kw):
            called["n"] += 1
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("cat AGENTS.md", cwd="../")
        assert r["ok"] is False
        assert "目标越界" in r["error"]
        assert called["n"] == 0

    def test_cwd_runs_before_blacklist_check(self, monkeypatch, fake_settings) -> None:
        """cwd 校验顺序：先围栏、再黑名单。两者都错时，围栏先报（更准）。"""
        # 黑名单命令 + 越界 cwd → 应报"目标越界"
        r = exec_tools.run_cmd("rm -rf /", cwd="/etc")
        assert r["ok"] is False
        # 黑名单报错前缀是 "命令被拦截"，围栏报错前缀是 "目标越界"
        assert "目标越界" in r["error"]


# -------------------- run_cmd: env 参数 --------------------

class TestRunCmdEnv:
    def test_default_env_is_none(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true")
        # 不传 env → subprocess.run 不应收到 env 键（让 Python 走默认 os.environ）
        assert "env" not in captured["kwargs"]

    def test_env_passed_through(self, monkeypatch, fake_settings) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("true", env={"FOO": "bar", "BAZ": "qux"})
        assert r["ok"] is True
        assert captured["kwargs"]["env"] == {"FOO": "bar", "BAZ": "qux"}

    def test_empty_env_dict_still_passed(self, monkeypatch, fake_settings) -> None:
        """显式空 dict 与 None 的语义不同：前者让子进程拿到空环境。

        这里只锁定"用户传的空 dict 仍然会到 subprocess"——具体是否清空
        os.environ 是 subprocess.run 的语义 (Python 3.9+ 视为"不继承")。
        """
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd("true", env={})
        assert r["ok"] is True
        assert captured["kwargs"]["env"] == {}

    def test_non_str_value_returns_ok_false(self, monkeypatch, fake_settings) -> None:
        """env 值必须是 str；混入 int / None / list 等异常类型直接 fail。"""
        r = exec_tools.run_cmd("true", env={"FOO": 12345})  # type: ignore[arg-type]
        assert r["ok"] is False
        assert "env 值" in r["error"]

    def test_non_str_key_returns_ok_false(self, monkeypatch, fake_settings) -> None:
        r = exec_tools.run_cmd("true", env={"OK": "good", 1: "bad"})  # type: ignore[arg-type]
        assert r["ok"] is False
        assert "env 键" in r["error"]

    def test_env_check_runs_after_cwd(self, monkeypatch, fake_settings) -> None:
        """env 校验放在 cwd 之后；cwd 已越界时 env 校验不应执行。"""
        called = {"n": 0}

        def fake_run(*a, **kw):
            called["n"] += 1
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        # 越界 cwd + 坏 env → 应报越界（不会撞到 env 校验）
        r = exec_tools.run_cmd("true", cwd="/etc", env={"FOO": 12345})  # type: ignore[arg-type]
        assert r["ok"] is False
        assert "目标越界" in r["error"]
        assert called["n"] == 0


# -------------------- run_cmd: type hint 兼容性 --------------------

class TestRunCmdSignature:
    """5.3 引入新参数后，原有 (cmd, timeout_s) 调用方式必须继续工作。"""

    def test_positional_cmd_still_supported(self, monkeypatch, fake_settings) -> None:
        monkeypatch.setattr(
            exec_tools.subprocess, "run",
            lambda *a, **kw: _fake_completed(),
        )
        # 5.2 之前的写法：run_cmd("echo hi")
        r = exec_tools.run_cmd("echo hi")
        assert r["ok"] is True

    def test_keyword_timeout_still_supported(self, monkeypatch, fake_settings) -> None:
        seen: list[int] = []

        def fake_run(cmd, **kwargs):
            seen.append(kwargs["timeout"])
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        exec_tools.run_cmd("true", timeout_s=7)
        assert seen == [7]

    def test_keyword_cwd_and_env_together(self, monkeypatch, fake_settings, tmp_path) -> None:
        captured: dict[str, Any] = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed()

        monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)
        r = exec_tools.run_cmd(
            "true",
            cwd="sandbox",
            env={"KEY": "val"},
            timeout_s=10,
        )
        assert r["ok"] is True
        kw = captured["kwargs"]
        assert kw["cwd"] == str((tmp_path / "sandbox").resolve())
        assert kw["env"] == {"KEY": "val"}
        assert kw["timeout"] == 10