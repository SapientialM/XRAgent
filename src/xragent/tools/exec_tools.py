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


def _coerce_int(value: Any, default: int, *, min_value: int = 0) -> int:
    """把任意值规范化成 ``int``, 且 ``>= min_value``。

    收敛 ``run_cmd`` / ``_truncate_output`` 里散落的"任意值 → 正整数"
    强转逻辑, 避免每次新增输出参数都要重写一遍 ``isinstance(...)`` 三连。
    失败兜底统一走 ``default``, 不抛异常 — 工具 handler 的入参校验应该是
    "宽容 + 兜底", 而不是 ``TypeError`` 冒到 LLM 面前。

    Args:
        value: 待归一化的值。None / bool / 非数值字符串 / 容器 → fallback。
        default: 兜底值（已满足 ``>= min_value`` 的契约由调用方保证）。
        min_value: 最小允许值; 传入值 < min_value 一律 fallback 到 default,
            避免负数 / 0 等导致 ``subprocess.run(timeout=0)`` 立刻报
            ``ValueError: timeout may not be negative`` 这类不友好错误。

    Returns:
        int: ``int(value)`` 当且仅当它是 int/float 且 ``>= min_value``;
        否则 ``default``。

    Examples:
        >>> _coerce_int(5, 30)
        5
        >>> _coerce_int(0, 30, min_value=1)
        30
        >>> _coerce_int(-3, 30, min_value=1)
        30
        >>> _coerce_int(None, 30)
        30
        >>> _coerce_int(True, 30)  # bool 是 int 子类, 显式拒绝
        30
        >>> _coerce_int("5", 30)
        30
    """
    if value is None or isinstance(value, bool):
        return default
    if not isinstance(value, (int, float)):
        return default
    n: int = int(value)
    if n < min_value:
        return default
    return n


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
        head_chars: 保留前 N 字;0 表示只保留尾部。负数 / 非数值 → 兜底为 0。
        tail_chars: 保留后 N 字;与 ``head_chars`` 之和是输出字符上限。
            负数 / 非数值 → 兜底为 :data:`OUTPUT_TAIL_LIMIT`。

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

    # 走公共 helper 兜底: 负数 / 非整数 / bool → default, 不再各写一遍 isinstance 三连
    head: int = _coerce_int(head_chars, default=0)
    tail: int = _coerce_int(tail_chars, default=OUTPUT_TAIL_LIMIT)

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
    """归一化 timeout_s 到合法正整数。

    非正数 / None / bool / 非数值 → 默认 :data:`DEFAULT_TIMEOUT_S`,
    避免 ``subprocess.run(timeout=0)`` 抛 ``ValueError`` 冒到 LLM 面前。
    复用 :func:`_coerce_int` 保证兜底语义与 head/tail 一致。
    """
    return _coerce_int(timeout_s, default=DEFAULT_TIMEOUT_S, min_value=1)


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