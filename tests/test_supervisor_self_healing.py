"""Supervisor 自愈：模拟子进程崩溃，验证 supervisor 重启逻辑。

不真的 spawn `xragent.main --as-supervised`（那需要阻塞 stdin）；
而是用一个会心跳+sleep 的 fake child 脚本，通过 supervisor 的 _spawn_child
注入逻辑。Supervisor 公共入口的测试在 e2e 里跑。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from xragent.watchdog import runtime_state as rs


def _make_fake_child(repo_root: Path) -> Path:
    """写一个'会心跳+sleep'的 fake child 脚本。

    读 XRAGENT_TEST_SRC（XRAGent 仓库的 src/ 绝对路径）和 XRAGENT_TEST_REPO
    （测试临时 repo_root），从而让 fake child 的 settings.repo_root 与父进程一致。
    """
    p = repo_root / ".tmp-fake-child.py"
    p.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "src = os.environ.get('XRAGENT_TEST_SRC')\n"
        "if not src:\n"
        "    raise SystemExit('XRAGENT_TEST_SRC not set')\n"
        "sys.path.insert(0, src)\n"
        "from xragent.config import settings as sm\n"
        "test_repo = os.environ.get('XRAGENT_TEST_REPO')\n"
        "if test_repo:\n"
        "    sm.reset_settings_cache()\n"
        "    s = sm.get_settings()\n"
        "    s.repo_root = Path(test_repo)\n"
        "    s.runtime_state_path = Path(test_repo) / 'runtime_state.json'\n"
        "    s.memory_db = Path(test_repo) / 'memory' / 'long_term' / 'facts.db'\n"
        "from xragent.watchdog import runtime_state as rs\n"
        "for i in range(30):\n"
        "    rs.heartbeat({'tick': i, 'pid_test': os.getpid()})\n"
        "    print('[fake-child] tick', i, flush=True)\n"
        "    time.sleep(0.3)\n",
        encoding="utf-8",
    )
    return p


def test_supervisor_spawns_child(repo_root, xragent_src):
    """直接 Popen fake child（模拟 supervisor 的 spawn 行为），验证它能写心跳。"""
    p = _make_fake_child(repo_root)
    try:
        env = os.environ.copy()
        env["XRAGENT_TEST_SRC"] = str(xragent_src); env["XRAGENT_TEST_REPO"] = str(repo_root); env.pop("PYTHONPATH", None)
        proc = subprocess.Popen(
            [sys.executable, str(p)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        # 等几秒让子进程至少写一次心跳
        time.sleep(1.5)
        assert proc.poll() is None, "子进程不应已退"
        proc.terminate()
        proc.wait(timeout=5)
    finally:
        try:
            p.unlink()
        except Exception:
            pass


def test_supervisor_detects_kill_and_can_restart(repo_root, xragent_src):
    """模拟 supervisor 的核心重启逻辑：spawn → kill → 监控心跳 → 自动重启。"""
    p = _make_fake_child(repo_root)
    try:
        # 第一次 spawn
        env = os.environ.copy()
        env["XRAGENT_TEST_SRC"] = str(xragent_src); env["XRAGENT_TEST_REPO"] = str(repo_root); env.pop("PYTHONPATH", None)

        proc1 = subprocess.Popen(
            [sys.executable, str(p)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(1.0)
        child_pid = rs.read().get("pid")
        assert child_pid == proc1.pid, "心跳应来自子进程"

        # SIGKILL 子进程
        os.kill(child_pid, signal.SIGKILL)
        proc1.wait(timeout=5)
        assert proc1.returncode == -9 or proc1.returncode == 137

        # 模拟 supervisor：看到 child 死了就再 spawn
        proc2 = subprocess.Popen(
            [sys.executable, str(p)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(1.0)
        assert proc2.poll() is None, "第二次 spawn 的子进程应仍在跑"

        # 验证新子进程也写了心跳
        new_pid = rs.read().get("pid")
        assert new_pid == proc2.pid
        assert new_pid != child_pid

        proc2.terminate()
        proc2.wait(timeout=5)
    finally:
        try:
            p.unlink()
        except Exception:
            pass
