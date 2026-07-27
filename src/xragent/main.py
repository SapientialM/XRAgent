"""XRAgent CLI 入口。

子命令：
  (default)        交互式 ReAct 循环（stdin 双源输入）
  --smoke          跑一次 mock 自我介绍，验证闭环
  --serve          启动 HTTP 父母通道 + ReAct 后台循环
  --as-supervised  被 supervisor 拉起时使用，定期写 heartbeat
  --freeze         禁用 propose_self_replace / terminate
  --once "<text>"  处理一条用户输入后退出
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time

from .config.settings import get_settings, reset_settings_cache
from .core.react_loop import ReActLoop
from .hitl.gate import HitlGate
from .memory.manager import MemoryManager
from .tools.registry import build_default_registry
from .watchdog import runtime_state as rs


def _print_hello() -> None:
    print("=" * 60)
    print("  XRAgent · 息壤 · v0.1")
    print("=" * 60)
    print("输入自然语言即可对话；Ctrl-D 退出。")
    print()


def cmd_smoke() -> int:
    from .core.backend import MockBackend
    backend = MockBackend()
    loop = ReActLoop(backend=backend, on_heartbeat=rs.heartbeat)
    out = loop.run("自我介绍一下")
    print(f"[smoke] turn_id={out['turn_id']}")
    print(f"[smoke] answer={out['answer'][:200]}")
    print(f"[smoke] wall_ms={out['wall_ms']} tokens_in={out['tokens_in']}")
    if out["error"]:
        print(f"[smoke] ERROR: {out['error']}")
        return 1
    return 0


def cmd_once(text: str, freeze: bool) -> int:
    if freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()
    out = ReActLoop(on_heartbeat=rs.heartbeat).run(text)
    print(out["answer"])
    return 0 if not out["error"] else 1


def cmd_interactive(freeze: bool, with_http: bool = False) -> int:
    """双源输入循环。

    - stdin TTY 且未开 HTTP：stdin reader 线程把行入队。
    - with_http=True：HTTP /message 入同一个队列；GET /last-answer 暴露最后一次输出。
    """
    if freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()
    _print_hello()
    loop = ReActLoop(on_heartbeat=rs.heartbeat)
    s = get_settings()
    stop_event = threading.Event()
    input_queue: "queue.Queue" = queue.Queue()
    last_answer_box: dict = {"answer": "", "ts": 0.0}

    if with_http:
        from .http_server import start_server_background, register_answer_sink, register_input_queue
        register_answer_sink(last_answer_box)
        register_input_queue(input_queue)
        start_server_background(loop)
        print(f"[serve] HTTP on http://{s.http_host}:{s.http_port}/  (POST /message, GET /last-answer, GET /health)")

    def heartbeat_worker():
        while not stop_event.is_set():
            try:
                rs.heartbeat()
            except Exception:
                pass
            stop_event.wait(s.heartbeat_interval_s)
    threading.Thread(target=heartbeat_worker, daemon=True).start()

    def stdin_reader():
        while not stop_event.is_set():
            try:
                line = input("you> ")
            except EOFError:
                input_queue.put(None)
                return
            line = line.strip()
            if line:
                input_queue.put(line)
    if sys.stdin.isatty() and not with_http:
        threading.Thread(target=stdin_reader, daemon=True).start()

    def handle_line(line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        if line in ("/quit", "/exit"):
            return False
        if line.startswith("/"):
            if line == "/tools":
                print("tools:", ", ".join(loop.registry.names()))
            elif line == "/memory":
                m = MemoryManager()
                for f in m.recent(5):
                    print(f"  [{f.category}] {f.content}")
            elif line == "/diary":
                from .tools.diary_tools import diary_write
                diary_write(title="manual", body="user requested /diary")
                print("diary updated")
            elif line == "/snapshot":
                tags = loop.snapshot.list_snapshots()
                print("snapshots:")
                for tg in tags[-10:]:
                    print(f"  {tg}")
            else:
                print("commands: /tools /memory /diary /snapshot /quit")
            return True
        out = loop.run(line)
        print(f"xr> {out['answer']}")
        last_answer_box["answer"] = out["answer"]
        last_answer_box["ts"] = time.time()
        return True

    try:
        while True:
            try:
                item = input_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                print("\n[exit]")
                return 0
            if not handle_line(item):
                return 0
    except KeyboardInterrupt:
        print("\n[exit]")
        return 0
    finally:
        stop_event.set()


def cmd_serve(freeze: bool) -> int:
    return cmd_interactive(freeze=freeze, with_http=True)


def cmd_supervised() -> int:
    s = get_settings()
    print(f"[supervised] pid={os.getpid()} heartbeat_interval={s.heartbeat_interval_s}s", flush=True)
    rs.heartbeat({"supervised": True})
    return cmd_interactive(freeze=False, with_http=False)


def main() -> int:
    parser = argparse.ArgumentParser(prog="xragent", description="XRAgent 息壤")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--once", type=str, default=None)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--as-supervised", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()

    if args.freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()

    if args.smoke:
        return cmd_smoke()
    if args.once:
        return cmd_once(args.once, args.freeze)
    if args.serve:
        return cmd_serve(args.freeze)
    if args.as_supervised:
        return cmd_supervised()
    return cmd_interactive(args.freeze, with_http=False)


if __name__ == "__main__":
    sys.exit(main())
