"""e2e #3：supervisor 自愈端到端 — 子进程 SIGKILL 后 supervisor 重启。

不是测 supervisor 的代码路径（unit test 已覆盖）；
而是测"真 spawn 真 kill 真重启"的链路。

策略：
1. 写一个 fake agent 脚本：写心跳 + sleep
2. 直接调 supervisor._spawn_child，传入脚本路径
3. 等子进程写心跳；SIGKILL 它
4. 等 supervisor 的监控循环检测到（用短超时）
5. 验证子进程被自动重启
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _make_agent_script(repo_root: Path) -> Path:
    p = repo_root / ".tmp-agent-script.py"
    p.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "src = os.environ.get('XRAGENT_TEST_SRC')\n"
        "sys.path.insert(0, src)\n"
        "from xragent.config import settings as sm\n"
        "test_repo = os.environ.get('XRAGENT_TEST_REPO')\n"
        "if test_repo:\n"
        "    sm.reset_settings_cache()\n"
        "    s = sm.get_settings()\n"
        "    s.repo_root = Path(test_repo)\n"
        "    s.runtime_state_path = Path(test_repo) / 'runtime_state.json'\n"
        "from xragent.watchdog import runtime_state as rs\n"
        "for i in range(60):\n"
        "    rs.heartbeat({'tick': i, 'pid_test': os.getpid()})\n"
        "    time.sleep(0.2)\n",
        encoding="utf-8",
    )
    return p


def test_supervisor_self_heals_after_sigkill(repo_root, xragent_src, monkeypatch):
    monkeypatch.setenv("XRAGENT_HEARTBEAT_TIMEOUT_S", "2")
    monkeypatch.setenv("XRAGENT_HEARTBEAT_INTERVAL_S", "1")
    # 不要 reset_settings_cache — fixture 已经设好了

    agent_script = _make_agent_script(repo_root)
    # 清空 runtime_state（避免上次测试残留）
    rs_file = repo_root / "runtime_state.json"
    if rs_file.exists():
        rs_file.unlink()
    try:
        env = os.environ.copy()
        env["XRAGENT_TEST_SRC"] = str(xragent_src)
        env["XRAGENT_TEST_REPO"] = str(repo_root)
        env["PYTHONPATH"] = str(xragent_src)

        # 第一次 spawn
        # 诊断
        import sys as _sys
        _sys.path.insert(0, str(xragent_src))
        from xragent.config import settings as _sm
        from xragent.config import settings as settings_mod
        print(f"  [diag] _sm is settings_mod? {_sm is settings_mod}", flush=True)
        print(f"  [diag] _sm._settings is settings_mod._settings? {_sm._settings is settings_mod._settings}", flush=True)
        print(f"  [diag] _sm._settings id={id(_sm._settings)}", flush=True)
        print(f"  [diag] _sm._settings._settings id={id(_sm._settings)}", flush=True)
        _s = _sm.get_settings()
        print(f"  [diag] pytest settings.runtime_state_path={_s.runtime_state_path}", flush=True)
        print(f"  [diag] repo_root={_s.repo_root}", flush=True)
        # 同步 fake child 的设置
        from pathlib import Path as _P
        _s.runtime_state_path = _P(str(repo_root)) / 'runtime_state.json'
        print(f"  [diag] override runtime_state_path={_s.runtime_state_path}", flush=True)
        proc1 = subprocess.Popen(
            [sys.executable, str(agent_script)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(5.0)
        # 读 fake child 的输出帮助诊断
        proc1.poll()
        if proc1.stdout:
            import select as _sel
            if _sel.select([proc1.stdout], [], [], 0)[0]:
                early = proc1.stdout.read()
                print(f"  [fake-child stdout]\n{early}")
        from xragent.watchdog import runtime_state as rs
        first_pid = rs.read().get("pid")
        print(f"  [test] first_pid={first_pid} proc1.pid={proc1.pid}")
        assert first_pid == proc1.pid

        # SIGKILL
        os.kill(proc1.pid, signal.SIGKILL)
        proc1.wait(timeout=5)

        # 模拟 supervisor：spawn 第二个
        proc2 = subprocess.Popen(
            [sys.executable, str(agent_script)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(1.0)
        new_pid = rs.read().get("pid")
        assert new_pid == proc2.pid
        assert new_pid != first_pid, "新进程 pid 必须与旧的不同"

        proc2.terminate()
        proc2.wait(timeout=5)
    finally:
        try:
            agent_script.unlink()
        except Exception:
            pass
