"""e2e #1：自我介绍 — ReAct 闭环 + diary 落盘。

不依赖 LLM（mock backend）；验证：
- ReAct loop 跑完一轮
- diary/turns/<id>.jsonl 写入
- diary/YYYY-MM-DD.md 写入
- facts.db 增加一条事实（可选）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_introduce_self(repo_root, xragent_src):
    """调用 --smoke 让 Agent 跑通自我介绍。"""
    env = __import__("os").environ.copy()
    env["XRAGENT_TEST_REPO"] = str(repo_root)
    env["XRAGENT_TEST_SRC"] = str(xragent_src)
    env["PYTHONPATH"] = str(xragent_src)
    env["XRAGENT_LLM_PROVIDER"] = "mock"

    proc = subprocess.run(
        [sys.executable, "-m", "xragent.main", "--smoke"],
        cwd=str(repo_root), env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"smoke failed: {proc.stderr}"
    assert "turn_id=" in proc.stdout
    assert "answer=" in proc.stdout

    # 落盘验证：fixture 已设好 settings（指向 tmp repo）
    sys.path.insert(0, str(xragent_src))
    from datetime import datetime
    from xragent.core.react_loop import ReActLoop
    from xragent.core.backend import MockBackend
    loop = ReActLoop(backend=MockBackend())
    out = loop.run("我是谁")
    assert out["answer"]

    today = datetime.now().strftime("%Y-%m-%d")
    diary = repo_root / "diary" / f"{today}.md"
    assert diary.exists(), f"diary {diary} 未生成"

    turns = list((repo_root / "diary" / "turns").glob("*.jsonl"))
    assert len(turns) >= 1
    last_turn = turns[-1]
    content = last_turn.read_text(encoding="utf-8").strip()
    rec = json.loads(content.splitlines()[-1])
    assert rec["turn_id"]
    assert rec["wall_ms"] >= 0
