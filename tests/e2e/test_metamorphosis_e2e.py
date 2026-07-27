"""e2e #2：金蝉脱皮端到端 — commit → py_compile → 世代谱 → runtime_state。

直接调用 metamorphose() 而非走 ReAct 工具，避免依赖 LLM。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_metamorphosis_end_to_end(repo_root, xragent_src):
    env = __import__("os").environ.copy()
    env["XRAGENT_TEST_REPO"] = str(repo_root)
    env["XRAGENT_TEST_SRC"] = str(xragent_src)

    # 在 tmp repo 里放一个可编译的 src/
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "module_a.py").write_text("A = 1\n", encoding="utf-8")
    (src / "module_b.py").write_text("B = 2\n", encoding="utf-8")

    # 写一个 in-process 测试脚本（不走 subprocess，因为要共享 settings）
    runner = repo_root / ".tmp-metamorphose-runner.py"
    runner.write_text(
        f"import os, sys\n"
        f"sys.path.insert(0, '{xragent_src}')\n"
        f"os.environ['XRAGENT_TEST_REPO'] = '{repo_root}'\n"
        f"from pathlib import Path\n"
        f"from xragent.config import settings as sm\n"
        f"sm.reset_settings_cache()\n"
        f"s = sm.get_settings()\n"
        f"s.repo_root = Path('{repo_root}')\n"
        f"s.runtime_state_path = Path('{repo_root}') / 'runtime_state.json'\n"
        f"s.memory_db = Path('{repo_root}') / 'memory' / 'long_term' / 'facts.db'\n"
        f"s.generations_log = Path('{repo_root}') / 'evolve' / 'generations.jsonl'\n"
        f"from xragent.evolve.metamorphosis import metamorphose\n"
        f"res = metamorphose('e2e 测试蜕皮闭环')\n"
        f"print('OK', res['ok'], 'compile_count=', len(res['compile_results']), 'head=', res['head_after'][:8])\n",
        encoding="utf-8",
    )
    try:
        proc = __import__("subprocess").run(
            [sys.executable, str(runner)],
            cwd=str(repo_root), env=env, capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"runner failed: {proc.stderr}\n{proc.stdout}"
        assert "OK True" in proc.stdout
        assert "compile_count= 2" in proc.stdout or "compile_count= 3" in proc.stdout  # 2 src + 1 evolve?

        # 验证世代谱写入
        gens_log = repo_root / "evolve" / "generations.jsonl"
        assert gens_log.exists()
        lines = gens_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        rec = json.loads(lines[-1])
        assert rec["reason"] == "e2e 测试蜕皮闭环"
        assert rec["compile_ok"] is True

        # 验证 runtime_state.json 写了 metamorphosis_pending
        rs_file = repo_root / "runtime_state.json"
        assert rs_file.exists()
        rs_data = json.loads(rs_file.read_text(encoding="utf-8"))
        assert rs_data.get("metamorphosis_pending")
        assert rs_data["metamorphosis_pending"]["compile_ok"] is True
    finally:
        try:
            runner.unlink()
        except Exception:
            pass


def test_metamorphosis_blocks_when_frozen(repo_root, xragent_src, monkeypatch):
    """evolution_enabled=false 时 propose_self_replace 被工具集移除。

    spawn 子进程验证（避免 pytest in-process settings cache 干扰）。
    """
    import sys, os, subprocess, json
    sys.path.insert(0, str(xragent_src))

    script = repo_root / ".tmp-frozen-check.py"
    script.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {str(xragent_src)!r})\n"
        "from xragent.config import settings as sm\n"
        "sm.reset_settings_cache()\n"
        "from xragent.tools.registry import build_default_registry\n"
        "import json\n"
        "result = {\n"
        "    'evolution_enabled': sm.get_settings().evolution_enabled,\n"
        "    'names': build_default_registry().names(),\n"
        "}\n"
        "print('XRCHECK_JSON_BEGIN', json.dumps(result), 'XRCHECK_JSON_END')\n",
        encoding="utf-8",
    )
    try:
        env_f = os.environ.copy()
        env_f["XRAGENT_EVOLUTION_ENABLED"] = "false"
        env_f["PYTHONPATH"] = str(xragent_src)
        proc = subprocess.run(
            [sys.executable, "-W", "ignore", str(script)],
            cwd=str(repo_root), env=env_f, capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0, f"frozen check failed: stderr={proc.stderr}\nstdout={proc.stdout}"
        import re
        m = re.search(r"XRCHECK_JSON_BEGIN (.+?) XRCHECK_JSON_END", proc.stdout)
        assert m, f"no JSON marker: stdout={proc.stdout}"
        result = json.loads(m.group(1))
        assert result["evolution_enabled"] is False
        assert "propose_self_replace" not in result["names"], f"frozen 后仍注册: {result['names']}"
        assert "terminate" not in result["names"]

        env_t = os.environ.copy()
        env_t["XRAGENT_EVOLUTION_ENABLED"] = "true"
        env_t["PYTHONPATH"] = str(xragent_src)
        proc = subprocess.run(
            [sys.executable, "-W", "ignore", str(script)],
            cwd=str(repo_root), env=env_t, capture_output=True, text=True, timeout=15,
        )
        m = re.search(r"XRCHECK_JSON_BEGIN (.+?) XRCHECK_JSON_END", proc.stdout)
        result = json.loads(m.group(1))
        assert result["evolution_enabled"] is True
        assert "propose_self_replace" in result["names"]
    finally:
        try:
            script.unlink()
        except Exception:
            pass
