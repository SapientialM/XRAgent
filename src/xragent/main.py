"""XRAgent CLI 入口。"""
from __future__ import annotations

import argparse
import os
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


def cmd_interactive(freeze: bool) -> int:
    if freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()
    _print_hello()
    loop = ReActLoop(on_heartbeat=rs.heartbeat)
    s = get_settings()
    stop_event = threading.Event()

    def heartbeat_worker():
        while not stop_event.is_set():
            try:
                rs.heartbeat()
            except Exception:
                pass
            stop_event.wait(s.heartbeat_interval_s)

    t = threading.Thread(target=heartbeat_worker, daemon=True)
    t.start()
    try:
        while True:
            try:
                line = input("you> ")
            except EOFError:
                print("\n[exit]")
                return 0
            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit"):
                return 0
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
                continue
            out = loop.run(line)
            print(f"xr> {out['answer']}")
    finally:
        stop_event.set()


def cmd_serve(freeze: bool) -> int:
    from .http_server import start_server_background
    if freeze:
        os.environ["XRAGENT_EVOLUTION_ENABLED"] = "false"
        reset_settings_cache()
    _print_hello()
    loop = ReActLoop(on_heartbeat=rs.heartbeat)
    start_server_background(loop)
    print("[serve] HTTP server up; POST /message to feed; /health for status")
    return cmd_interactive(freeze=freeze)


def cmd_supervised() -> int:
    s = get_settings()
    print(f"[supervised] pid={os.getpid()} heartbeat_interval={s.heartbeat_interval_s}s", flush=True)
    rs.heartbeat({"supervised": True})
    return cmd_interactive(freeze=False)


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
    return cmd_interactive(args.freeze)


if __name__ == "__main__":
    sys.exit(main())
