"""Supervisor：24h 守护子 Agent。"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from ..config.settings import get_settings
from . import runtime_state as rs


def _spawn_child(extra_args: list[str] | None = None) -> subprocess.Popen:
    """按 XRAGENT_SPAWN_MODE 决定 spawn autonomous 还是 supervised 子 Agent。

    默认 autonomous（自驱动循环，无需 stdin/HTTP）。
    设 XRAGENT_SPAWN_MODE=supervised 退回交互式。
    """
    import os
    s = get_settings()
    mode = os.environ.get("XRAGENT_SPAWN_MODE", "autonomous").lower()
    if mode == "autonomous":
        mode_args = ["--autonomous", "--interval", str(max(30, s.heartbeat_interval_s))]
    else:
        mode_args = ["--as-supervised"]
    cmd = [sys.executable, "-m", "xragent.main", *mode_args, *(extra_args or [])]
    return subprocess.Popen(
        cmd, cwd=str(s.repo_root), stdout=sys.stdout, stderr=sys.stderr,
        start_new_session=True,
    )


def run_forever() -> None:
    s = get_settings()
    failures = 0
    while True:
        rs.heartbeat({"supervisor_pid": os.getpid()})
        state = rs.read()
        if state.get("restart_suppressed"):
            print("[supervisor] restart_suppressed detected; exit.", flush=True)
            return
        child = _spawn_child()
        print(f"[supervisor] spawned child pid={child.pid}", flush=True)
        last_heartbeat_seen = rs.read().get("heartbeat_ts", 0)
        try:
            while True:
                rc = child.poll()
                if rc is not None:
                    print(f"[supervisor] child exited rc={rc}", flush=True)
                    if rc == 0 and state.get("restart_suppressed"):
                        return
                    break
                now = time.time()
                hb = rs.read().get("heartbeat_ts", 0)
                if hb > last_heartbeat_seen:
                    last_heartbeat_seen = hb
                elif now - hb > s.heartbeat_timeout_s:
                    print(f"[supervisor] heartbeat timeout ({int(now-hb)}s); killing child", flush=True)
                    try:
                        os.killpg(os.getpgid(child.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
                    break
                time.sleep(s.heartbeat_interval_s)
        except KeyboardInterrupt:
            try:
                os.killpg(os.getpgid(child.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            child.wait(timeout=10)
            return

        rc = child.poll() if child.poll() is not None else -1
        if rc != 0:
            failures += 1
            rs.bump_restart()
            print(f"[supervisor] failure #{failures}", flush=True)
            if failures >= s.restart_max_failures:
                print(f"[supervisor] reached max failures {s.restart_max_failures}; stop.", flush=True)
                return
            time.sleep(min(2 ** failures, 30))
        else:
            failures = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="XRAgent supervisor (24h watchdog)")
    parser.add_argument("--once", action="store_true", help="跑一次就退出")
    args = parser.parse_args()
    if args.once:
        s = get_settings()
        child = _spawn_child(["--smoke"])
        rc = child.wait()
        sys.exit(rc)
    run_forever()


if __name__ == "__main__":
    main()
