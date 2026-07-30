"""tests/test_evolve_tools.py

覆盖 src/xragent/tools/evolve_tools.py 的 5 项改动:
  1. 公共 helper _load_runtime_state / _save_runtime_state
  2. 公共 helper _check_compile
  3. propose_self_replace 新参数 dry_run (跳过 commit/push/kill)
  4. terminate 新参数 suppress_restart (默认 True / False 不写 restart_suppressed)
  5. type hint 不会漂移 LLM 工具契约的键集合

依赖 conftest.repo_root 提供的 tmp 仓库根 (含 .git/)。
terminate 真发 SIGTERM 会杀测试进程,所以一律 monkeypatch os.kill;
propose_self_replace 真 metamorphose 会 push 网络,全部走 monkeypatch。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from xragent.config import settings as settings_mod
from xragent.config.settings import get_settings
from xragent.tools import evolve_tools


# -------------------- fixtures --------------------

@pytest.fixture
def no_kill(monkeypatch):
    """拦住 os.kill,防止 terminate 真的杀进程。"""
    calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))

    monkeypatch.setattr(evolve_tools.os, "kill", fake_kill)
    return calls


@pytest.fixture
def evolution_on():
    """显式确保 evolution_enabled=True (部分测试默认 fixture 已开)。"""
    s = get_settings()
    orig = s.evolution_enabled
    object.__setattr__(s, "evolution_enabled", True)
    yield s
    object.__setattr__(s, "evolution_enabled", orig)


@pytest.fixture
def evolution_off():
    """把 evolution_enabled 关掉,验证门控。"""
    s = get_settings()
    orig = s.evolution_enabled
    object.__setattr__(s, "evolution_enabled", False)
    yield s
    object.__setattr__(s, "evolution_enabled", orig)


def _seed_src(repo_root: Path, files: dict[str, str]) -> Path:
    """在 repo_root/src/ 下写一组 .py 文件 (key=相对路径,value=源码)。"""
    src = repo_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


# -------------------- _load_runtime_state --------------------

class TestLoadRuntimeState:
    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert evolve_tools._load_runtime_state(tmp_path / "nope.json") == {}

    def test_corrupt_file_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json {{{", encoding="utf-8")
        assert evolve_tools._load_runtime_state(p) == {}

    def test_valid_file_returns_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "ok.json"
        p.write_text(json.dumps({"a": 1, "b": "x"}), encoding="utf-8")
        assert evolve_tools._load_runtime_state(p) == {"a": 1, "b": "x"}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert evolve_tools._load_runtime_state(p) == {}


# -------------------- _save_runtime_state --------------------

class TestSaveRuntimeState:
    def test_roundtrip_preserves_unicode(self, tmp_path: Path) -> None:
        p = tmp_path / "rt.json"
        state = {"restart_suppressed": True, "terminate_reason": "父母要求停下"}
        evolve_tools._save_runtime_state(p, state)
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == state

    def test_writes_indented_json(self, tmp_path: Path) -> None:
        p = tmp_path / "ind.json"
        evolve_tools._save_runtime_state(p, {"x": 1})
        text = p.read_text(encoding="utf-8")
        # indent=2 至少换行一次
        assert "\n" in text


# -------------------- _check_compile --------------------

class TestCheckCompile:
    def test_missing_src_dir_returns_empty(self, tmp_path: Path) -> None:
        # 用 fresh tmp_path 不依赖 conftest,边界场景更纯净
        assert evolve_tools._check_compile(tmp_path) == []

    def test_valid_files_all_ok(self, repo_root: Path) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
        results = evolve_tools._check_compile(repo_root)
        assert len(results) == 2
        assert all(r["ok"] for r in results)
        # 文件路径是相对 repo_root 的 posix 字符串
        assert {r["file"] for r in results} == {"src/a.py", "src/pkg/b.py"}

    def test_syntax_error_marked_failed(self, repo_root: Path) -> None:
        _seed_src(repo_root, {"good.py": "ok = True\n", "bad.py": "def (\n"})
        results = evolve_tools._check_compile(repo_root)
        by_file = {r["file"]: r for r in results}
        assert by_file["src/good.py"]["ok"] is True
        assert by_file["src/bad.py"]["ok"] is False
        assert "error" in by_file["src/bad.py"]
        assert by_file["src/bad.py"]["error"]  # 非空


# -------------------- propose_self_replace(dry_run) --------------------

class TestProposeSelfReplaceDryRun:
    def test_dry_run_skips_metamorphose(
        self, repo_root: Path, monkeypatch, evolution_on
    ) -> None:
        _seed_src(repo_root, {"x.py": "x = 1\n"})

        called = {"n": 0}

        def fake_metamorphose(**kwargs):
            called["n"] += 1
            return {"ok": True}

        monkeypatch.setattr(evolve_tools, "metamorphose", fake_metamorphose)

        r = evolve_tools.propose_self_replace("trial", dry_run=True)
        assert r["dry_run"] is True
        assert r["head_after"] is None
        assert r["ok"] is True
        assert len(r["compile_results"]) == 1
        assert called["n"] == 0  # 关键：metamorphose 没被调

    def test_dry_run_returns_compile_errors(
        self, repo_root: Path, monkeypatch, evolution_on
    ) -> None:
        _seed_src(repo_root, {"bad.py": "def (\n"})
        monkeypatch.setattr(evolve_tools, "metamorphose", lambda **kw: {"ok": True})

        r = evolve_tools.propose_self_replace("trial", dry_run=True)
        assert r["ok"] is False
        assert r["dry_run"] is True
        assert any(not cr["ok"] for cr in r["compile_results"])

    def test_dry_run_does_not_write_generations(
        self, repo_root: Path, monkeypatch, evolution_on
    ) -> None:
        from xragent.evolve.generations import list_generations
        _seed_src(repo_root, {"x.py": "x = 1\n"})
        monkeypatch.setattr(evolve_tools, "metamorphose", lambda **kw: {"ok": True})

        before = len(list_generations())
        evolve_tools.propose_self_replace("trial", dry_run=True)
        after = len(list_generations())
        assert before == after  # 没写

    def test_evolution_disabled_blocks_even_dry_run(
        self, repo_root: Path, monkeypatch, evolution_off
    ) -> None:
        _seed_src(repo_root, {"x.py": "x = 1\n"})
        called = {"n": 0}

        def fake_check(*_a, **_kw):
            called["n"] += 1
            return []

        monkeypatch.setattr(evolve_tools, "_check_compile", fake_check)
        r = evolve_tools.propose_self_replace("trial", dry_run=True)
        assert r == {"ok": False, "blocked_by": "evolution_disabled"}
        # 关键：连编译检查都不做（避免冻结时还跑 py_compile）
        assert called["n"] == 0

    def test_normal_path_delegates_to_metamorphose(
        self, repo_root: Path, monkeypatch, evolution_on
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_metamorphose(reason, entry):
            seen["reason"] = reason
            seen["entry"] = entry
            return {"ok": True, "head_after": "abc123"}

        monkeypatch.setattr(evolve_tools, "metamorphose", fake_metamorphose)

        r = evolve_tools.propose_self_replace("trial", entry="src/foo.py")
        assert r == {"ok": True, "head_after": "abc123"}
        assert seen == {"reason": "trial", "entry": "src/foo.py"}


# -------------------- terminate(suppress_restart) --------------------

class TestTerminateSuppressRestart:
    def test_default_sets_restart_suppressed(
        self, repo_root: Path, evolution_on, no_kill
    ) -> None:
        from xragent.memory.manager import MemoryManager
        m = MemoryManager()
        before = len(m.recall_range(category="lifecycle"))

        r = evolve_tools.terminate("父母要求停下")

        # 返回值兜底
        assert r == {"ok": True, "reason": "父母要求停下"}
        # SIGTERM 已发
        assert len(no_kill) == 1
        # runtime_state.json: restart_suppressed + terminate_reason 都写
        state = json.loads((repo_root / "runtime_state.json").read_text(encoding="utf-8"))
        assert state[evolve_tools.RUNTIME_STATE_KEY_RESTART_SUPPRESSED] is True
        assert state[evolve_tools.RUNTIME_STATE_KEY_TERMINATE_REASON] == "父母要求停下"
        # lifecycle memory fact 落了
        after = len(m.recall_range(category="lifecycle"))
        assert after == before + 1

    def test_suppress_restart_false_omits_key(
        self, repo_root: Path, evolution_on, no_kill
    ) -> None:
        evolve_tools.terminate("误判,记录但不自杀", suppress_restart=False)

        assert len(no_kill) == 1  # SIGTERM 还是发了 (工具语义)
        state = json.loads((repo_root / "runtime_state.json").read_text(encoding="utf-8"))
        # 关键：restart_suppressed *不在* state 里 → supervisor 会按惯例重启
        assert evolve_tools.RUNTIME_STATE_KEY_RESTART_SUPPRESSED not in state
        assert state[evolve_tools.RUNTIME_STATE_KEY_TERMINATE_REASON] == "误判,记录但不自杀"

    def test_suppress_restart_false_does_not_clobber_existing(
        self, repo_root: Path, evolution_on, no_kill
    ) -> None:
        # 先放一个无关 key 到 state
        path = repo_root / "runtime_state.json"
        path.write_text(json.dumps({"heartbeat_ts": 12345}), encoding="utf-8")

        evolve_tools.terminate("误判", suppress_restart=False)

        state = json.loads(path.read_text(encoding="utf-8"))
        assert state["heartbeat_ts"] == 12345  # 保留
        assert state[evolve_tools.RUNTIME_STATE_KEY_TERMINATE_REASON] == "误判"
        assert evolve_tools.RUNTIME_STATE_KEY_RESTART_SUPPRESSED not in state

    def test_suppress_restart_true_overrides_false(
        self, repo_root: Path, evolution_on, no_kill
    ) -> None:
        # 先用 False 写一次留下 terminate_reason 但没 restart_suppressed
        evolve_tools.terminate("phase 1", suppress_restart=False)
        # 再用 True 触发"真正停"
        evolve_tools.terminate("phase 2", suppress_restart=True)

        state = json.loads((repo_root / "runtime_state.json").read_text(encoding="utf-8"))
        assert state[evolve_tools.RUNTIME_STATE_KEY_RESTART_SUPPRESSED] is True
        # 后写覆盖前写 (terminate_reason 是最后一次的值)
        assert state[evolve_tools.RUNTIME_STATE_KEY_TERMINATE_REASON] == "phase 2"


# -------------------- type-hint 契约 --------------------

class TestTypeContract:
    """type hint 引入不应漂移 LLM 工具契约的键集合。"""

    def test_evolution_disabled_keys(self, repo_root: Path, evolution_off) -> None:
        r = evolve_tools.propose_self_replace("x")
        assert set(r.keys()) == {"ok", "blocked_by"}

    def test_dry_run_keys(self, repo_root: Path, evolution_on) -> None:
        _seed_src(repo_root, {"x.py": "x = 1\n"})
        r = evolve_tools.propose_self_replace("x", dry_run=True)
        assert set(r.keys()) == {"ok", "compile_results", "dry_run", "head_after"}
        assert isinstance(r["ok"], bool)
        assert isinstance(r["dry_run"], bool)
        assert isinstance(r["head_after"], type(None))
        assert isinstance(r["compile_results"], list)

    def test_terminate_keys(self, repo_root: Path, evolution_on, no_kill) -> None:
        r = evolve_tools.terminate("x")
        assert set(r.keys()) == {"ok", "reason"}
        assert isinstance(r["ok"], bool)
        assert isinstance(r["reason"], str)