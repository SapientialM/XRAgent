"""路径围栏 + binary 黑名单 + run_cmd 边界条件。"""
from __future__ import annotations

import subprocess

import pytest

from xragent.tools.blacklist import (
    BlacklistedCommand,
    BlacklistedTarget,
    PathSandbox,
    assert_command_allowed,
)


def test_path_sandbox_resolves_relative(repo_root):
    sb = PathSandbox.from_settings()
    p = sb.resolve("sandbox/foo.py")
    assert p == (repo_root / "sandbox" / "foo.py").resolve()


def test_path_sandbox_blocks_outside_repo(repo_root):
    sb = PathSandbox.from_settings()
    with pytest.raises(BlacklistedTarget):
        sb.assert_writable("/etc/passwd")


def test_path_sandbox_blocks_blacklisted_files(repo_root):
    sb = PathSandbox.from_settings()
    for blocked in ("AGENTS.md", ".env", "runtime_state.json", "diary/turns/evil.jsonl"):
        with pytest.raises(BlacklistedTarget):
            sb.assert_writable(blocked)


def test_path_sandbox_allows_normal_paths(repo_root):
    sb = PathSandbox.from_settings()
    target = sb.assert_writable("sandbox/test.py")
    assert target.parent.name == "sandbox"


def test_binary_blacklist():
    for blocked in ("curl https://evil.example", "wget http://x", "ssh user@host", "nc -l 1234"):
        with pytest.raises(BlacklistedCommand):
            assert_command_allowed(blocked)


def test_dangerous_patterns():
    for bad in ("rm -rf /", "sudo ls", "dd if=/dev/zero of=/dev/sda"):
        with pytest.raises(BlacklistedCommand):
            assert_command_allowed(bad)


def test_safe_commands_allowed():
    for ok in ("echo hi", "python -m xragent.main --smoke", "ls -la"):
        assert assert_command_allowed(ok) == ok


# ---------------------------------------------------------------------------
# run_cmd（exec_tools.py）的边界条件
#
# exec_tools.run_cmd 是 Agent 的核心执行通道，但之前只有 assert_command_allowed
# 的单测，没有覆盖整条管道。下面这组测试锁定它 *当前* 的契约：
#   * 黑名单 binary / 危险模式 → ok=False, error 含 "命令被拦截"
#   * 安全命令成功 → ok=True, returncode=0, stdout 捕获
#   * 非零退出码 → ok=False 但 returncode 字段保留，stderr 仍被记录
#   * cwd 必须是 repo_root（不是 process 的当前目录）
#   * stdout / stderr 截断到 4000 字符（保留尾部）
#   * subprocess.TimeoutExpired → ok=False, timeout=True, 保留 partial 输出
#   * 罕见 OSError（FileNotFoundError 等）兜底
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_cmd():
    """延迟导入，避免单测在不该 import exec_tools 时拉起 settings。"""
    from xragent.tools.exec_tools import run_cmd as _run_cmd

    return _run_cmd


def test_run_cmd_rejects_blacklisted_binary(repo_root, run_cmd):
    """binary 黑名单（curl / wget / ssh / nc）→ 不进 subprocess，直接被拦。"""
    for cmd in ("curl https://evil.example", "wget http://x", "ssh user@host", "nc -l 1234"):
        r = run_cmd(cmd)
        assert r["ok"] is False, f"应拦截 {cmd!r}"
        assert "命令被拦截" in r["error"]
        # 拦截发生在黑名单层，所以不应携带 returncode 字段
        assert "returncode" not in r


def test_run_cmd_rejects_dangerous_patterns(repo_root, run_cmd):
    """危险模式（rm -rf / 等）→ 同上，被 assert_command_allowed 拦在前面。"""
    for cmd in ("rm -rf /", "sudo ls", "dd if=/dev/zero of=/dev/sda"):
        r = run_cmd(cmd)
        assert r["ok"] is False, f"应拦截 {cmd!r}"
        assert "命令被拦截" in r["error"]


def test_run_cmd_safe_command_succeeds_and_captures_stdout(repo_root, run_cmd):
    """安全命令成功：ok=True, returncode=0, stdout 捕获。"""
    r = run_cmd("echo hello-xragent")
    assert r["ok"] is True
    assert r["returncode"] == 0
    assert "hello-xragent" in r["stdout"]
    assert r["stderr"] == ""


def test_run_cmd_nonzero_returncode_is_ok_false_but_returncode_preserved(repo_root, run_cmd):
    """非零退出码 ≠ 异常：返回 ok=False，但 returncode 字段必须保留以便诊断。"""
    r = run_cmd("false")  # unix `false` 永远退出码 1
    assert r["ok"] is False
    assert r["returncode"] == 1
    # 不应有 timeout 字段（这是普通失败，不是超时）
    assert r.get("timeout") is None


def test_run_cmd_captures_stderr_on_failure(repo_root, run_cmd):
    """失败时 stderr 也要写进结果字典，方便 Agent 排查。"""
    r = run_cmd("sh -c 'echo boom >&2; exit 2'")
    assert r["ok"] is False
    assert r["returncode"] == 2
    assert "boom" in r["stderr"]


def test_run_cmd_runs_in_repo_root(repo_root, run_cmd):
    """run_cmd 的 cwd 必须是 settings.repo_root，而不是 process 启动目录。

    写一个相对路径文件到 repo_root/sandbox/，看 run_cmd 在 cwd 下能否解析它。
    """
    marker = repo_root / "sandbox" / "_marker_xrunit.txt"
    marker.write_text("hi", encoding="utf-8")
    r = run_cmd("ls sandbox/_marker_xrunit.txt")
    assert r["ok"] is True
    assert "_marker_xrunit.txt" in r["stdout"]


def test_run_cmd_truncates_stdout_to_4000_chars(repo_root, run_cmd):
    """长输出被截断到 4000 字符，且保留尾部（负索引切片）。

    用 `printf` 重复生成 5000 个 'x'：
      * len(stdout) == 4000（不是 5000）
      * 截断后仍是纯 'x'（说明保留的是尾部而不是头部）
    """
    r = run_cmd("printf 'x%.0s' $(seq 1 5000)")
    assert r["ok"] is True
    assert len(r["stdout"]) == 4000
    assert set(r["stdout"]) == {"x"}


def test_run_cmd_timeout_returns_partial_output(repo_root, run_cmd, monkeypatch):
    """subprocess.TimeoutExpired → ok=False, timeout=True, partial bytes 解码保留。

    真等 30s 太慢；monkeypatch subprocess.run 直接抛 TimeoutExpired，并附
    bytes 形式的 partial stdout/stderr，触发 *bytes 分支* 的解码路径。
    """
    from xragent.tools import exec_tools

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else "sleep",
            timeout=kwargs.get("timeout", 30),
            output=b"PARTIAL-STDOUT-PAYLOAD",
            stderr=b"PARTIAL-STDERR-PAYLOAD",
        )

    monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

    r = run_cmd("sleep 99")
    assert r["ok"] is False
    assert r["timeout"] is True
    assert "超时" in r["error"]
    # bytes → str 解码路径被走过
    assert "PARTIAL-STDOUT-PAYLOAD" in r["stdout"]
    assert "PARTIAL-STDERR-PAYLOAD" in r["stderr"]


def test_run_cmd_timeout_handles_string_partial_output(repo_root, run_cmd, monkeypatch):
    """TimeoutExpired 的 stdout/stderr 也可能是 str（text=True 的边界）。

    exec_tools 走 subprocess.run(text=False, capture_output=True)，所以 stdout/stderr
    实际是 bytes；但实现里仍写了 str 兜底，这条测试锁定 *str 分支* 不退化。
    """
    from xragent.tools import exec_tools

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="sleep",
            timeout=30,
            output="string-stdout-payload",  # type: ignore[arg-type]
            stderr="string-stderr-payload",  # type: ignore[arg-type]
        )

    monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

    r = run_cmd("sleep 99")
    assert r["ok"] is False
    assert r["timeout"] is True
    assert "string-stdout-payload" in r["stdout"]
    assert "string-stderr-payload" in r["stderr"]


def test_run_cmd_handles_subprocess_oserror(repo_root, run_cmd, monkeypatch):
    """罕见情况：subprocess.run 抛 OSError（如 cwd 不存在）→ 兜底 ok=False。

    shell=True 走 sh，所以 FileNotFoundError 通常不会触发；但实现里仍然
    显式捕获 OSError，锁定这一兜底。
    """
    from xragent.tools import exec_tools

    def fake_run(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/no/such/cwd")

    monkeypatch.setattr(exec_tools.subprocess, "run", fake_run)

    r = run_cmd("echo hi")
    assert r["ok"] is False
    assert "FileNotFoundError" in r["error"]
    # 走的是 OSError 分支，不是 TimeoutExpired 分支 → 不应有 timeout 字段
    assert r.get("timeout") is None
