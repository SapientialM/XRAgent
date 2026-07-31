"""HTTP 父母通道的便捷启动 helper。

## 为什么

``main.py`` 里 :func:`xragent.main.cmd_interactive` 的 ``if with_http`` 分支和
:func:`xragent.main.cmd_autonomous` 的 HTTP server 启动段，是同一段 6+ 行模板：

    from .http_server import register_answer_sink, register_input_queue, start_server_background
    last_answer_box: dict = {"answer": "", "ts": 0.0}
    register_answer_sink(last_answer_box)
    register_input_queue(<input_queue>)
    start_server_background(loop)
    print(f"[…] HTTP on http://{host}:{port}/…")

差别只有两点：日志前缀（``[serve]`` vs ``[autonomous instance=HHMMSS]``）+
URL 后的 hint 文案 + OSError 兜底（``cmd_interactive`` 之前没有，``cmd_autonomous``
有；新版两边都带兜底，行为更一致）。

抽到 :func:`setup_http_parents_channel` 后，两处都只剩 3-4 行；写第三个
HTTP 父母通道的入口（比如 ``cmd_supervised`` 以后想带 HTTP）时也不会再抄出
第三个变体。

## 边界

- **不创建 input_queue**：调用方自己 ``queue.Queue()``，再传进来。原因：
  cmd_interactive 的 input_queue 要复用给 REPL（HTTP 和 stdin 二选一）；
  cmd_autonomous 的 input_queue 是独立的 parent_msg_queue（永远独立于
  REPL queue）。helper 不知道业务语义，让调用方决定。
- **OSError 吞掉并 print**：端口占用等 bind 失败不应让主进程崩。
  其它异常会冒泡（说明是编程错误，不是环境问题）。
- **register_* 调用顺序固定为 answer_sink → input_queue → start_server**：
  顺序对正确性无影响（http_server.py 内部用 module-level 变量存），
  但稳定顺序让日志和代码 diff 更可读。
- **不返回 loop**：调用方已经持有 loop，helper 只需要在内部用一次。
- **``extra_hint`` 留空字符串**：cmd_interactive URL 后面不需要 hint；
  cmd_autonomous 写「POST /message 即可插队」。
"""
from __future__ import annotations

import queue
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.react_loop import ReActLoop


def setup_http_parents_channel(
    loop: "ReActLoop",
    input_queue: "queue.Queue[str]",
    *,
    instance_id: str | None = None,
    extra_hint: str = "",
) -> dict:
    """注册 input queue + answer sink + 启动 HTTP server。

    调用方需要的 input_queue 由它自己创建（cmd_interactive 复用已有的
    REPL queue；cmd_autonomous 新建一个 parent_msg_queue），helper 只
    负责 register + start + print 这一段。OSError bind 失败时吞掉并
    print（不冒泡到调用方）；其它异常仍会冒泡。

    Args:
        loop: 已构造好的 :class:`ReActLoop`；会被传给
            :func:`xragent.http_server.start_server_background`。
        input_queue: 进程级共享队列；HTTP ``POST /message`` 会 ``put``。
        instance_id: 可选实例标识（autonomous 多 child 时区分日志）；
            ``None`` 时日志前缀就是 ``[serve]``；传值时变成
            ``[serve instance=HHMMSS]``。
        extra_hint: URL print 后的附加提示文本（autonomous 写「POST
            /message 即可插队」；cmd_interactive 留空字符串）。

    Returns:
        创建好的 ``last_answer_box`` dict（形如
        ``{"answer": "", "ts": 0.0}``）。调用方应在每轮
        ``loop.run()`` 完后**就地更新** ``answer`` 与 ``ts`` 字段，
        不要替换整个 dict——http_server.py 通过对象 id 持有引用，
        替换会让 ``/last-answer`` 永远读到旧的空 box。
    """
    # 内部 import 避免 util → http_server 的循环依赖风险；
    # util/heartbeat.py / util/jsonl_utils.py 也用同模式（按需 import）。
    from ..config.settings import get_settings
    from ..http_server import (
        register_answer_sink,
        register_input_queue,
        start_server_background,
    )
    s = get_settings()
    last_answer_box: dict = {"answer": "", "ts": 0.0}
    register_answer_sink(last_answer_box)
    register_input_queue(input_queue)
    tag = f" instance={instance_id}" if instance_id else ""
    hint = f"  ({extra_hint})" if extra_hint else ""
    try:
        start_server_background(loop)
        print(f"[serve{tag}] HTTP on http://{s.http_host}:{s.http_port}/{hint}", flush=True)
    except OSError as e:
        # bind 失败（如端口占用）：吞掉，不让主进程崩；与原 cmd_autonomous
        # 行为一致；cmd_interactive 之前没兜底，新版统一带（更安全）。
        print(f"[serve{tag}] HTTP server bind failed: {e}", flush=True)
    return last_answer_box


__all__ = ["setup_http_parents_channel"]