"""shell 命令执行。"""
from __future__ import annotations

import subprocess
from typing import Any

from .blacklist import assert_command_allowed


# === 常量：暴露给测试 / 外部调用方统一引用 ===
DEFAULT_TIMEOUT_S: int = 30
OUTPUT_TAIL_LIMIT: int = 4000


def _truncate_output(value: Any, limit: int = OUTPUT_TAIL_LIMIT) -> str:
    """把 subprocess 输出统一成 str 并保留尾部 limit 字符。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-limit:]
    if isinstance(value, str):
        return value[-limit:]
    return repr(value)[-limit:]


def _fail(error: str, /, **extras: Any) -> dict[str, Any]:
    """ok=False 字典工厂。positional-only error; extras 显式传入才出现。"""
    out: dict[str, Any] = {"ok": False, "error": error}
    out.update(extras)
    return out


def _resolve_timeout(timeout_s: int | float | None) -> int:
    """归一化 timeout_s 到合法正整数。"""
    if timeout_s is None or isinstance(timeout_s, bool):
        return DEFAULT_TIMEOUT_S
    if not isinstance(timeout_s, (int, float)):
        return DEFAULT_TIMEOUT_S
    if timeout_s <= 0:
        return DEFAULT_TIMEOUT_S
    return int(timeout_s)


def run_cmd(cmd: str, timeout_s: int | float | None = None) -> dict[str, Any]:
    """在 settings.repo_root 下执行 shell 命令。

    Args:
        cmd: shell 命令字符串
        timeout_s: 超时秒数。None / 非正数 / 非数值 → 默认 30s。
    """
    effective_timeout = _resolve_timeout(timeout_s)

    try:
        assert_command_allowed(cmd)
    except Exception as e:
        return _fail(f"命令被拦截: {type(e).__name__}: {e}")

    from ..config.settings import get_settings
    s = get_settings()

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(s.repo_root),
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as e:
        return _fail(
            f"超时（>{effective_timeout}s）: {e}",
            timeout=True,
            stdout=_truncate_output(e.stdout),
            stderr=_truncate_output(e.stderr),
        )
    except (FileNotFoundError, OSError) as e:
        return _fail(f"{type(e).__name__}: {e}")

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _truncate_output(proc.stdout),
        "stderr": _truncate_output(proc.stderr),
    }