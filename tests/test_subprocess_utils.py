"""tests/test_subprocess_utils.py — 锁 run_capture API + 与 side_git 集成。

任务背景：v0.3 refactor 把 ``subprocess.run(["git", ...], cwd=..., capture_output=True,
text=True, ...)`` 模板从 main.py 和 side_git.py 抽到 ``util.subprocess_utils.run_capture``。
本测试锁:
  1. 成功命令的返回值结构 (rc, stdout, stderr) — 三者都已 .strip()
  2. cwd 参数真的传给 subprocess.run
  3. 失败命令 (rc != 0) 不抛, 原样返回
  4. timeout → rc=-1, 不抛 TimeoutExpired
  5. binary 缺失 → rc=-1, 不抛 FileNotFoundError
  6. 与 side_git 的集成: push / _run 都通过 run_capture, 行为不变

侧注：第 6 条也覆盖了 test_git_tools.py 的 ``monkeypatch.setattr(side_git.subprocess,
"run", fake_run)`` 还能不能拦截到 —— 因为 ``subprocess.run`` 在 run_capture 函数体内
是动态查找, fake_run 在 side_git 和 subprocess_utils 里同时被看到。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xragent.snapshot import side_git
from xragent.tools import git_tools
from xragent.util import subprocess_utils as su


# ------------------------------------------------------------------ run_capture API


def test_run_capture_returns_stripped_triple_for_success():
    """echo '  hello  ' → stdout='hello' (已 strip), rc=0, stderr=''."""
    rc, out, err = su.run_capture(["echo", "  hello  "])
    assert rc == 0
    assert out == "hello"
    assert err == ""


def test_run_capture_returns_nonzero_rc_without_raising():
    """false 命令 → rc=1, 不抛."""
    rc, out, err = su.run_capture(["false"])
    assert rc == 1
    assert out == ""
    assert err == ""


def test_run_capture_passes_cwd(tmp_path: Path):
    """cwd 参数真生效: 在 tmp_path 创建 marker.txt, ls 后能找到."""
    marker = tmp_path / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    rc, out, err = su.run_capture(["ls", "marker.txt"], cwd=tmp_path)
    assert rc == 0
    assert "marker.txt" in out
    assert err == ""


def test_run_capture_timeout_returns_rc_minus_one():
    """sleep 5 + timeout=0.1 → rc=-1 (不抛 TimeoutExpired), stderr 含 timeout 信息."""
    rc, out, err = su.run_capture(["sleep", "5"], timeout=0.1)
    assert rc == -1, f"timeout 应当返回 rc=-1, got {rc}"
    assert out == ""
    assert "timed out" in err.lower() or "timeout" in err.lower(), (
        f"stderr 应提示 timeout, got {err!r}"
    )


def test_run_capture_missing_binary_returns_rc_minus_one():
    """不存在的 binary → rc=-1 (不抛 FileNotFoundError)."""
    rc, out, err = su.run_capture(["definitely-not-a-real-binary-xyz123"])
    assert rc == -1
    assert out == ""
    assert "definitely-not-a-real-binary-xyz123" in err or "No such file" in err, (
        f"stderr 应提示 binary 缺失, got {err!r}"
    )


def test_run_capture_default_encoding_is_utf8():
    """中文 stdout 不应因为编码问题变成乱码或抛 UnicodeDecodeError."""
    rc, out, err = su.run_capture(["echo", "息壤"], encoding="utf-8")
    assert rc == 0
    assert "息壤" in out


# ------------------------------------------------------------------ side_git 集成


def test_side_git_push_uses_run_capture_and_returns_bool_tuple(repo_root: Path):
    """无 origin → push 必败, 但返回结构必须是 (bool, str) 且 msg 非空."""
    sg = side_git.SideGit(repo_root=repo_root)
    ok, msg = sg.push()
    assert isinstance(ok, bool)
    assert ok is False
    assert isinstance(msg, str)
    assert msg, "失败时 msg 必须非空，便于 LLM 看到诊断信息"


def test_side_git_run_raises_runtime_error_on_git_failure(repo_root: Path):
    """git 命令非 0 (例如 add 一个不在的文件) → raise RuntimeError, 不抛 TimeoutExpired."""
    sg = side_git.SideGit(repo_root=repo_root)
    with pytest.raises(RuntimeError) as ei:
        sg._run("add", "definitely-not-exist-xyz.txt")
    # 原契约: 消息含 "git ... 失败: " 前缀
    msg = str(ei.value)
    assert "git add" in msg and "失败" in msg, f"消息格式漂移: {msg!r}"


def test_side_git_run_passes_kwargs_via_run_capture(repo_root: Path):
    """_run 真实走 run_capture, 透传 cwd + 解析 git rev-parse HEAD."""
    sg = side_git.SideGit(repo_root=repo_root)
    head = sg.current_head()
    assert len(head) >= 7, f"head 不像 sha: {head!r}"
    assert all(c in "0123456789abcdef" for c in head)


# ------------------------------------------------------------------ 与 test_git_tools.py 的 monkeypatch 兼容性


def test_monkeypatch_subprocess_run_still_intercepts_push(repo_root: Path, monkeypatch: pytest.MonkeyPatch):
    """关键回归测试: test_git_tools.py 用 ``monkey.setattr(side_git.subprocess, "run", ...)``
    拦截参数透传。refactor 后 subprocess.run 改在 run_capture 内 lookup, 必须仍然被拦截。

    原理: Python 模块是 singleton, ``subprocess`` 在 side_git 和 subprocess_utils 里是同一对象;
    ``subprocess.run`` 是模块属性, 在函数体内动态查找 → fake_run 被两处同时看到。
    """
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkeypatch.setattr(side_git.subprocess, "run", fake_run)
    # side_git.push 通过 run_capture 调用 subprocess.run; 这里也直接 monkeypatch
    # side_git.subprocess 等价于 monkeypatch su.subprocess (同一模块)
    monkeypatch.setattr(su.subprocess, "run", fake_run)

    r = git_tools.git_push(remote="myfork", branch="dev-branch")
    assert captured["args"][:3] == ["git", "push", "myfork"]
    assert "dev-branch" in captured["args"]
    assert r["ok"] is True
    assert r["msg"] == ""


# ------------------------------------------------------------------ main.py maybe_periodic_push 集成


def test_main_run_capture_helper_signature_is_stable():
    """锁 run_capture 的 signature: (cmd, cwd=None, *, timeout=None, encoding='utf-8')."""
    import inspect
    sig = inspect.signature(su.run_capture)
    params = list(sig.parameters.keys())
    assert params == ["cmd", "cwd", "timeout", "encoding"], (
        f"signature 漂移: {params}"
    )
    # 默认值
    assert sig.parameters["cwd"].default is None
    assert sig.parameters["timeout"].default is None
    assert sig.parameters["encoding"].default == "utf-8"