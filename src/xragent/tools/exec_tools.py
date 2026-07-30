"""shell 命令执行。"""
from __future__ import annotations

import subprocess
from typing import Any

from .blacklist import assert_command_allowed


# === 常量：暴露给测试 / 外部调用方统一引用 ===
DEFAULT_TIMEOUT_S: int = 30
OUTPUT_TAIL_LIMIT: int = 4000

# 输出被截断时夹在前/后两段之间的"省略提示"文案。带换行让 LLM 容易
# 在流式输出里扫到边界。
_OMITTED_MARKER: str = "\n...[省略 {n} 字]...\n"


def _truncate_output(
    value: Any,
    *,
    head_chars: int = 0,
    tail_chars: int = OUTPUT_TAIL_LIMIT,
) -> str:
    """把 subprocess 输出统一成 str,按需保留 head + tail 双段。

    三种典型场景:
      * ``head_chars=0`` (默认) → 只保留尾部 ``tail_chars`` 字。
        与旧版行为完全一致, 调用方不需要改。
      * ``head_chars > 0`` 且输出总长 > ``head_chars + tail_chars`` →
        输出 ``<head段>\\n...[省略 N 字]...\\n<tail段>``, 头尾都看得到,
        排查超长输出 (pytest 报错、stack trace) 时少打几次重跑。
      * 输出总长 ≤ ``head_chars + tail_chars`` → 原样返回 (不插省略提示)。

    Args:
        value: subprocess stdout/stderr,可能是 ``None`` / ``bytes`` /
            ``str`` / 其他任意类型 (``int``、异常对象等)。
        head_chars: 保留前 N 字;0 表示只保留尾部。
        tail_chars: 保留后 N 字;与 ``head_chars`` 之和是输出上限。

    Returns:
        统一 ``str``,头部 (可选) + 省略提示 (可选) + 尾部。
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        text: str = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        text = repr(value)

    # 兜底: 负数 / 非整数 → 当作 0, 避免 slice 出错
    head: int = max(0, int(head_chars)) if isinstance(head_chars, int) and not isinstance(head_chars, bool) else 0
    tail: int = max(0, int(tail_chars)) if isinstance(tail_chars, int) and not isinstance(tail_chars, bool) else OUTPUT_TAIL_LIMIT

    total: int = head + tail
    n: int = len(text)
    if n <= total:
        return text
    if head == 0:
        # 向后兼容: 老调用方只关心尾巴
        return text[-tail:]
    return f"{text[:head]}{_OMITTED_MARKER.format(n=n - total)}{text[-tail:]}"


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


def run_cmd(
    cmd: str,
    timeout_s: int | float | None = None,
    *,
    output_head_chars: int = 0,
    output_tail_chars: int = OUTPUT_TAIL_LIMIT,
) -> dict[str, Any]:
    """在 settings.repo_root 下执行 shell 命令。

    Args:
        cmd: shell 命令字符串
        timeout_s: 超时秒数。None / 非正数 / 非数值 → 默认 30s。
        output_head_chars: 输出保留前 N 字 (与 ``output_tail_chars`` 配合);
            0 表示只保留尾部, 与旧版契约一致。
        output_tail_chars: 输出保留后 N 字。``head + tail`` 即输出字符上限。

    Returns:
        ``dict[str, Any]``, LLM 工具契约字段:
            * ``ok`` (bool): True 表示 returncode == 0
            * 成功时附加 ``returncode`` / ``stdout`` / ``stderr`` (int / str / str)
            * 超时时附加 ``timeout=True`` + 部分 stdout/stderr
            * 黑名单 / OSError 时只附加 ``error`` (str)
    """
    effective_timeout: int = _resolve_timeout(timeout_s)

    try:
        assert_command_allowed(cmd)
    except Exception as e:
        return _fail(f"命令被拦截: {type(e).__name__}: {e}")

    from ..config.settings import get_settings
    s = get_settings()

    try:
        proc: subprocess.CompletedProcess = subprocess.run(
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
            stdout=_truncate_output(e.stdout, head_chars=output_head_chars, tail_chars=output_tail_chars),
            stderr=_truncate_output(e.stderr, head_chars=output_head_chars, tail_chars=output_tail_chars),
        )
    except (FileNotFoundError, OSError) as e:
        return _fail(f"{type(e).__name__}: {e}")

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _truncate_output(proc.stdout, head_chars=output_head_chars, tail_chars=output_tail_chars),
        "stderr": _truncate_output(proc.stderr, head_chars=output_head_chars, tail_chars=output_tail_chars),
    }