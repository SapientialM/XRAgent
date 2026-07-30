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
    """Spawn 子 Agent；显式把 .env 内容注入子进程 env。

    不依赖 pydantic-settings 自己读 .env（pydantic-settings 不会把 env var 注入 os.environ，
    且子进程的 cwd=仓库根，理论上能读，但为了稳健性这里直接传 env）。

    spawn 模式由 XRAGENT_SPAWN_MODE 控制：autonomous（默认）/ supervised。
    """
    import os
    s = get_settings()
    mode = os.environ.get("XRAGENT_SPAWN_MODE", "autonomous").lower()
    if mode == "autonomous":
        mode_args = ["--autonomous", "--interval", str(max(30, s.heartbeat_interval_s))]
    else:
        mode_args = ["--as-supervised"]
    cmd = [sys.executable, "-m", "xragent.main", *mode_args, *(extra_args or [])]

    # 父进程 env + .env 解析
    child_env = os.environ.copy()
    env_path = s.repo_root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                child_env.setdefault(key, val)  # 不覆盖已有（launchd 显式设的优先）

    # 强制覆盖 PATH（launchd 默认 PATH 太短，没 /opt/homebrew/bin → git/python3 找不到）
    child_env["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    child_env.setdefault("HOME", "/Users/cm")
    child_env.setdefault("USER", "cm")
    return subprocess.Popen(
        cmd, cwd=str(s.repo_root), stdout=sys.stdout, stderr=sys.stderr,
        start_new_session=True, env=child_env,
    )


def run_forever() -> None:
    """守护主循环：拉起子 Agent、监控心跳、超时重启。

    流程（每轮迭代）:
        1. 写 ``runtime_state.json`` 标记 supervisor 自己存活 (供外部探活)。
        2. 若 ``runtime_state.restart_suppressed`` 为真 → 退出 (parents 主动停机信号)。
        3. ``waitpid(-1, WNOHANG)`` 收割所有 zombie 子进程。
        4. ``_spawn_child()`` 拉起新子进程, 父进程与子进程同 session 组
           (``start_new_session=True``), 便于用 ``killpg`` 整组杀。
        5. 内层循环每 ``heartbeat_interval_s`` 醒来一次:
             * 子进程 ``poll()`` 返回非 None → 自然退出, 准备下一轮
             * ``runtime_state.heartbeat_ts`` 超 ``heartbeat_timeout_s`` 未更新
               → 心跳超时, ``SIGTERM`` 杀进程组, break
             * KeyboardInterrupt (Ctrl-C) → 杀进程组后 return
        6. 退出码 != 0 → ``failures += 1``, 指数退避重启 (上限 30s);
           累计到 ``restart_max_failures`` 时整体退出。
           退出码 == 0 且 ``restart_suppressed`` → 退出 (干净关机路径)。

    Returns:
        None. 该函数只在以下两种情况下返回:
            * 收到 ``restart_suppressed`` 标志 (parents 主动停机)
            * 连续 ``restart_max_failures`` 次重启失败, 放弃自愈
    """
    s = get_settings()
    failures = 0
    while True:
        rs.heartbeat({"supervisor_pid": os.getpid()})
        state = rs.read()
        if state.get("restart_suppressed"):
            print("[supervisor] restart_suppressed detected; exit.", flush=True)
            return
        # 批量收割所有 zombie 子进程（POSIX waitpid -1 + WNOHANG）
        import os as _os
        while True:
            try:
                _zpid, _ = _os.waitpid(-1, _os.WNOHANG)
                if _zpid == 0:
                    break
            except ChildProcessError:
                break
            except Exception:
                break

        # 回收上一个 child（兜底）
        try:
            if "prev_child" in dir() and prev_child is not None:
                prev_child.wait(timeout=0)
        except Exception:
            pass

        child = _spawn_child()
        prev_child = child
        print(f"[supervisor] spawned child pid={child.pid}", flush=True)
        last_heartbeat_seen = rs.read().get("heartbeat_ts", 0)
        try:
            while True:
                rc = child.poll()
                if rc is not None:
                    print(f"[supervisor] child exited rc={rc}", flush=True)
                    # 回收 zombie
                    try:
                        child.wait(timeout=0)
                    except Exception:
                        pass
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
    """supervisor CLI 入口: 解析参数, 选择 ``run_forever()`` 还是单次 smoke。

    命令行参数:
        ``--once``: 不进守护循环, 直接 ``_spawn_child(["--smoke"])`` 跑一次子
        进程并 ``child.wait()``, 把子进程 returncode 作为本进程退出码返回。
        供 CI / 一次性排错用。

    退出码: 与被包装的子进程退出码一致 (无 ``--once`` 时, ``run_forever``
    永不返回直到触发停机信号)。
    """
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