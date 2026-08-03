"""``try/except Exception + print failed`` 模板 helper。

``main.py::cmd_autonomous`` 里有 3 处重复的
``except Exception as e: print(f"[autonomous] <X> failed: {e}", flush=True)``
模式（push / task gen / commit），抽到 :func:`print_guard` helper。失败时返回
``None``（调用方拿 ``None`` 决定 fallback：continue / sleep / 跳过 record_done
等），不返回 fallback 值，避免调用方忘记检查返回值导致 silent pass。

不引入 logging 模块：原 ``print(..., flush=True)`` 走 stdout，supervisor
redirect（``> runtime.log``）能抓到；改 logging 会增加 formatter / handler 配置，
且 capture 子进程里的 ``print`` 已经够用。
"""
from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def _format_failure_message(prefix: str, label: str, exc: BaseException) -> str:
    """构造 ``[{prefix}] {label} failed: <exc>`` 失败日志。

    集中一处便于维护：``tests/test_print_guard.py::test_prints_failure_with_default_prefix``
    与 ``test_prints_failure_with_custom_prefix`` 锁定该格式；将来要把失败事件改成
    结构化日志（JSON / telemetry）只需改这一处而不是 grep 整个仓库。
    """
    return f"[{prefix}] {label} failed: {exc}"


def print_guard(label: str, fn: Callable[[], T], *, prefix: str = "autonomous") -> T | None:
    """Run ``fn()``；异常时以 ``[prefix] {label} failed: {e}`` 形式 print 到 stdout。

    Args:
        label: 失败的简短描述（``"push"`` / ``"task gen"`` / ``"commit"``）。
        fn: 要保护的 callable。
        prefix: log prefix，默认 ``"autonomous"``，与 ``main.py::cmd_autonomous`` 一致。

    Returns:
        ``fn()`` 的返回值；异常时返回 ``None``。调用方需自行判断 ``None`` 决定
        是否 continue / sleep / 跳过后续步骤。

    Note:
        这里**不**返回 fallback 值（如 ``""`` / ``False`` / ``0``），因为调用方
        各自 fallback 不同：task gen 失败 → sleep 60s + continue；commit 失败
        → 跳过 commit-only 副作用但仍 ``record_done``；push 失败 → 跳过
        ``last_push_ts = now``。强行返回 fallback 反而要求调用方检查"是 fn 真
        返回还是 guard 兜的"，徒增分支。

        **只吞 Exception**：``KeyboardInterrupt`` / ``SystemExit`` 是
        ``BaseException`` 直接子类，向上冒泡，保证 SIGINT 与 ``sys.exit()`` 不被
        guard 吃掉。``test_does_not_swallow_keyboard_interrupt`` /
        ``test_does_not_swallow_system_exit`` 锁此边界。
    """
    try:
        return fn()
    except Exception as e:
        print(_format_failure_message(prefix, label, e), flush=True)
        return None


__all__ = ["print_guard"]
