"""XRAgent CLI 入口。

子命令：
  --smoke / --once / --serve / --as-supervised / --autonomous / --freeze
"""
from __future__ import annotations

import argparse
import os
import queue
import signal as _signal
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
    if freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()
    _print_hello()
    # autonomous 模式不打 turn tag（30s 一轮会刷屏 2000+/天）；只保留 stash 供 rollback
    loop = ReActLoop(on_heartbeat=rs.heartbeat, max_steps=40, tag_snapshots=False)
    s = get_settings()
    stop_event = threading.Event()
    input_queue: "queue.Queue" = queue.Queue()
    last_answer_box: dict = {"answer": "", "ts": 0.0}

    if with_http:
        from .http_server import start_server_background, register_answer_sink, register_input_queue
        register_answer_sink(last_answer_box)
        register_input_queue(input_queue)
        start_server_background(loop)
        print(f"[serve] HTTP on http://{s.http_host}:{s.http_port}/")

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


def cmd_autonomous(interval_s: int = 30, max_rounds: int = 0) -> int:
    """自驱动循环：无人值守也能跑。"""
    s = get_settings()
    print(f"[autonomous] pid={os.getpid()} interval={interval_s}s max_rounds={max_rounds or 'inf'}", flush=True)
    rs.heartbeat({"autonomous": True, "interval_s": interval_s})

    from .autonomous import next_task, record_done
    from .snapshot.side_git import SideGit

    stop = {"v": False}

    def _handle_term(signum, frame):
        stop["v"] = True
        print(f"\n[autonomous] received signal {signum}; will exit after current round", flush=True)
    _signal.signal(_signal.SIGTERM, _handle_term)
    _signal.signal(_signal.SIGINT, _handle_term)

    # autonomous 模式不打 turn tag（30s 一轮会刷屏 2000+/天）；只保留 stash 供 rollback
    loop = ReActLoop(on_heartbeat=rs.heartbeat, max_steps=40, tag_snapshots=False)
    sg = SideGit()
    rounds = 0
    try:
        while not stop["v"]:
            rounds += 1
            if max_rounds and rounds > max_rounds:
                print(f"[autonomous] reached max_rounds={max_rounds}", flush=True)
                break
            try:
                task = next_task()
            except Exception as e:
                print(f"[autonomous] task gen error: {e}; sleep 60s", flush=True)
                time.sleep(60)
                continue

            print(f"\n[autonomous] round {rounds}: {task['title']}", flush=True)
            try:
                out = loop.run(task["prompt"])
                err = out.get("error")
                summary = (out.get("answer") or "").strip()[:300]
                if err:
                    summary = f"ERROR: {err}\n{summary}"
            except Exception as e:
                out = {"turn_id": "n/a", "answer": "", "actions": [], "error": str(e), "wall_ms": 0}
                summary = f"exception: {e}"

            try:
                head = sg.add_all_and_commit(f"autonomous: {task['title'][:60]} (round {rounds})")
                if head:
                    print(f"[autonomous] committed {head[:8]}", flush=True)
            except Exception as e:
                print(f"[autonomous] commit failed: {e}", flush=True)

            record_done(task, out.get("turn_id", "n/a"), summary)
            print(f"[autonomous] done in {out.get('wall_ms', 0)}ms; sleep {interval_s}s", flush=True)
            time.sleep(interval_s)
    finally:
        rs.heartbeat({"autonomous": False, "rounds": rounds})
        print(f"[autonomous] exited after {rounds} rounds", flush=True)
    return 0


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
    parser.add_argument("--autonomous", action="store_true", help="自驱动循环")
    parser.add_argument("--interval", type=int, default=30, help="autonomous 每轮间隔秒")
    parser.add_argument("--max-rounds", type=int, default=0, help="autonomous 最大轮数（0=无限）")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()

    if args.freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()

    if args.smoke:
        return cmd_smoke()
    if args.once:
        return cmd_once(args.once, args.freeze)
    if args.autonomous:
        return cmd_autonomous(interval_s=args.interval, max_rounds=args.max_rounds)
    if args.serve:
        return cmd_serve(args.freeze)
    if args.as_supervised:
        return cmd_supervised()
    return cmd_interactive(args.freeze, with_http=False)


if __name__ == "__main__":
    sys.exit(main())
