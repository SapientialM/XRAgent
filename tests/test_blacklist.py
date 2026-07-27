"""路径围栏 + binary 黑名单。"""
from __future__ import annotations

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
