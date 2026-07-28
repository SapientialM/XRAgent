"""shell 命令执行。"""
from __future__ import annotations

import subprocess

from .blacklist import assert_command_allowed


def run_cmd(cmd: str) -> dict:
    try:
        assert_command_allowed(cmd)
    except Exception as e:
        return {"ok": False, "error": f"命令被拦截: {type(e).__name__}: {e}"}

    from ..config.settings import get_settings
    s = get_settings()

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(s.repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        # 部分输出可能已被捕获（partial capture），尽量保留供诊断。
        stdout = (e.stdout or b"")[-4000:] if isinstance(e.stdout, bytes) else (e.stdout or "")[-4000:]
        stderr = (e.stderr or b"")[-4000:] if isinstance(e.stderr, bytes) else (e.stderr or "")[-4000:]
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "error": f"超时（>30s）: {e}",
            "timeout": True,
            "stdout": stdout,
            "stderr": stderr,
        }
    except (FileNotFoundError, OSError) as e:
        # shell=True 时通常不会抛 FileNotFoundError（shell 会返回 127），
        # 但覆盖罕见场景（shell 缺失、cwd 不存在等）。
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }