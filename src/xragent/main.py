"""XRAgent CLI 入口。

子命令：
  --smoke / --once / --serve / --as-supervised / --autonomous / --freeze
"""
from __future__ import annotations

import argparse
import os
import queue
import signal as _signal
import subprocess
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
    """自驱动循环：无人值守也能跑；同时开 HTTP 通道让父母能随时插队。"""
    s = get_settings()
    # instance 标（让 log 不再"永远是 round 1"——能看到 supervisor 每次 spawn 的 child 实例）
    instance_id = time.strftime("%H%M%S")
    print(f"[autonomous] pid={os.getpid()} instance={instance_id} interval={interval_s}s max_rounds={max_rounds or 'inf'}", flush=True)
    rs.heartbeat({"autonomous": True, "interval_s": interval_s, "instance": instance_id})

    from .autonomous import next_task, record_done, task_queue_path
    from .snapshot.side_git import SideGit

    stop = {"v": False}

    def _handle_term(signum, frame):
        stop["v"] = True
        print(f"\n[autonomous instance={instance_id}] received signal {signum}; will exit after current round", flush=True)
    _signal.signal(_signal.SIGTERM, _handle_term)
    _signal.signal(_signal.SIGINT, _handle_term)

    # 父母 HTTP 通道：POST /message 把消息注入主循环（高优先级插队）
    from .http_server import start_server_background, register_input_queue
    parent_msg_queue: queue.Queue[str] = queue.Queue()
    register_input_queue(parent_msg_queue)

    # 独立线程消费 parent_msg_queue：有 message 立刻打断 round
    # 用 threading.Event 让主循环感知"被打断"
    interrupt_event = threading.Event()

    def _parent_consumer():
        while not stop["v"]:
            try:
                parent_text = parent_msg_queue.get(timeout=1.0)
                if not parent_text:
                    continue
                print(f"[autonomous instance={instance_id}] parent message (interrupting): {parent_text[:80]}", flush=True)
                # 立刻设 interrupt flag，让主循环跳出当前 round
                interrupt_event.set()
                # 跑 parent reply
                try:
                    p_out = loop.run(f"[from parent] {parent_text}")
                    reply = (p_out.get('answer') or '')[:300]
                    last_answer_box['answer'] = p_out.get('answer') or ''
                    last_answer_box['ts'] = time.time()
                    print(f"[autonomous] parent reply: {reply}", flush=True)
                except Exception as e:
                    print(f"[autonomous] parent reply error: {e}", flush=True)
                # 跑完后清 flag
                interrupt_event.clear()
            except Exception:
                pass

    threading.Thread(target=_parent_consumer, daemon=True).start()

    # 异步 heartbeat 线程：每 5s 写一次（即使 LLM 调用 30s+ supervisor 也不误判超时）
    def _heartbeat_loop():
        while not stop["v"]:
            try:
                rs.heartbeat()
            except Exception:
                pass
            if not stop["v"]:
                threading.Event().wait(5)
    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    # autonomous 模式不打 turn tag（30s 一轮会刷屏 2000+/天）；只保留 stash 供 rollback
    loop = ReActLoop(on_heartbeat=rs.heartbeat, max_steps=40, tag_snapshots=False)
    sg = SideGit()
    # 注册全局 last_answer sink：每次 loop.run() 跑完自动写到 /last-answer
    from .http_server import register_answer_sink
    last_answer_box = {"answer": "", "ts": 0.0}
    register_answer_sink(last_answer_box)
    # 真启动 HTTP server（接受 POST /message）
    try:
        start_server_background(loop)
        print(f"[autonomous instance={instance_id}] HTTP on http://{s.http_host}:{s.http_port}/  (POST /message 即可插队)", flush=True)
    except OSError as e:
        print(f"[autonomous instance={instance_id}] HTTP server bind failed: {e}", flush=True)
    rounds = 0
    last_push_ts = 0.0  # 0 = 下一次 commit 后立即 push；之后每 push_interval_minutes push 一次
    push_interval_s = max(60, s.push_interval_minutes * 60)

    def maybe_periodic_push(force: bool = False):
        nonlocal last_push_ts
        now = time.time()
        if not force and last_push_ts and (now - last_push_ts) < push_interval_s:
            return
        # 只在有未推 commit 时 push（HEAD 比 origin/main 新）
        try:
            ahead = subprocess.run(
                ["git", "rev-list", "--count", "origin/main..HEAD"],
                cwd=str(s.repo_root), capture_output=True, text=True, timeout=5,
            )
            n = int(ahead.stdout.strip() or 0)
        except Exception:
            n = 0
        if n == 0:
            last_push_ts = now
            return
        try:
            ok, msg = sg.push()
            if ok:
                print(f"[autonomous] pushed {n} commit(s) to origin/main", flush=True)
            else:
                print(f"[autonomous] push returned ok=False: {msg[:200]}", flush=True)
            last_push_ts = now
        except Exception as e:
            print(f"[autonomous] push failed: {e}", flush=True)

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
                    # 第一次 commit 后立即 push；之后每 push_interval_minutes
                    maybe_periodic_push(force=(last_push_ts == 0.0))
            except Exception as e:
                print(f"[autonomous] commit failed: {e}", flush=True)

            record_done(task, out.get("turn_id", "n/a"), summary)
            print(f"[autonomous] done in {out.get('wall_ms', 0)}ms; sleep {interval_s}s", flush=True)
            # 独立线程处理 parent_msg（不等 sleep；interrupt_event 也通知主循环）
            time.sleep(interval_s)
            maybe_periodic_push(force=False)
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
