"""后台心跳线程的通用启动器。

## 为什么

``main.py`` 里 :func:`xragent.main.cmd_interactive` 的 ``heartbeat_worker`` 和
:func:`xragent.main.cmd_autonomous` 的 ``_heartbeat_loop`` 是同一段 7 行模板：

    while not <stop>:
        try:
            rs.heartbeat()
        except Exception:
            pass
        wait(<interval>)

差别只有两点：停止条件（``threading.Event.is_set`` vs ``dict["v"]``）+ 间隔来源
（``settings.heartbeat_interval_s`` vs 写死 5s）。原代码两个函数分别写了一遍，
连 ``try / except Exception: pass`` 的"吞异常"细节都一致——典型的复制粘贴。

抽到 :func:`start_heartbeat_thread` 后，两处都只剩一行 ``start_heartbeat_thread(...)``
调用；新人写第三个心跳线程时也不会再抄出第四个变体。

## 边界

- 异常一律吞（``except Exception: pass``）——心跳失败不应让守护线程崩。
  若上层需要心跳失败告警，由 ``runtime_state.heartbeat`` 自己在写入端处理。
- ``stop_predicate`` 在每次循环开头、每次 wait 之前各调一次；保证响应延迟
  不超过 ``interval_s``，且退出时不会卡在 ``wait`` 上。
- 不持有 ``threading.Thread`` 句柄：调用方只关心"后台跑 + 退出时能停"。
  若以后需要 join()，再加返回 ``Thread`` 的 API。
- ``name`` 默认 ``"xragent-heartbeat"``，方便 ``threading.enumerate()`` 排错。
- daemon=True：父进程退出时不必显式 join。
"""
from __future__ import annotations

import threading
from typing import Callable

from ..watchdog import runtime_state as rs


def start_heartbeat_thread(
    stop_predicate: Callable[[], bool],
    interval_s: float,
    name: str = "xragent-heartbeat",
) -> threading.Thread:
    """启动一个后台心跳线程，按 ``interval_s`` 节拍调 :func:`rs.heartbeat`。

    线程函数本体::

        while not stop_predicate():
            try:
                rs.heartbeat()
            except Exception:
                pass
            if not stop_predicate():
                threading.Event().wait(interval_s)

    调用方拿到的是已经 ``start()`` 过的 :class:`threading.Thread` 实例；
    无需关心生命周期（``daemon=True`` 让进程退出时直接终止）。

    Args:
        stop_predicate: 无参 callable，返回 True 表示应停止循环。
            每次循环头 + 每次 wait 之前各调一次，保证响应延迟 ≤ ``interval_s``。
        interval_s: 两次 ``rs.heartbeat()`` 之间的间隔秒数；必须 > 0，
            否则 ``threading.Event().wait(0)`` 会立刻返回退化成忙循环。
        name: 线程名，便于 ``threading.enumerate()`` / 日志排错。

    Returns:
        已 ``start()`` 过的 :class:`threading.Thread`（daemon=True）。

    Examples:
        用 ``threading.Event`` 做停止条件::

            stop = threading.Event()
            start_heartbeat_thread(stop.is_set, settings.heartbeat_interval_s)

        用 ``dict`` 旗标做停止条件（autonomous 的 ``stop["v"]`` 风格）::

            stop = {"v": False}
            start_heartbeat_thread(lambda: stop["v"], interval_s=5)
    """

    def _loop() -> None:
        """心跳线程主体。

        行为契约（见模块 docstring 的"边界"一节）：

        1. 循环开头先检查 ``stop_predicate()``，避免停后还多调一次
           ``rs.heartbeat()``。
        2. ``rs.heartbeat()`` 抛任何异常都吞掉——心跳失败不能让守护线程
           崩，失败信息由 ``runtime_state`` 自己落盘。
        3. ``wait(interval_s)`` 之前再查一次 ``stop_predicate()``，确保
           退出时不会卡在 wait 上多撑一个 interval。

        闭包捕获 ``stop_predicate`` + ``interval_s``，不在外层暴露。
        """
        while not stop_predicate():
            try:
                rs.heartbeat()
            except Exception:
                pass
            if not stop_predicate():
                threading.Event().wait(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name=name)
    t.start()
    return t


__all__ = ["start_heartbeat_thread"]