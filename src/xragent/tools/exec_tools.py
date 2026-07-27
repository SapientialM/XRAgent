"""shell 命令执行。"""
from __future__ import annotations

import subprocess

from .blacklist import assert_command_allowed


def run_cmd(cmd: str) -> dict:
    try:
        assert_command_allowed(cmd)
    except Exception as e:
        return {"ok": False, "error": f"命令被拦截: {e}"}

    from ..config.settings import get_settings
    s = get_settings()

    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(s.repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
