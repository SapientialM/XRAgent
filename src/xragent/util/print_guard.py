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
    """
    try:
        return fn()
    except Exception as e:
        print(f"[{prefix}] {label} failed: {e}", flush=True)
        return None