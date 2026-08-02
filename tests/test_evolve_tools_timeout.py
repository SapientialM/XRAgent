"""tests/test_evolve_tools_timeout.py

覆盖 src/xragent/tools/evolve_tools.py v0.5.6 改动:
  1. 抽公共 helper ``_compile_one(path) -> str | None``
  2. ``_check_compile`` 新参数 ``timeout_s`` / ``max_workers`` (默认 None 保留串行快路径)
  3. ``COMPILE_TIMEOUT_S`` / ``COMPILE_MAX_WORKERS`` 常量
  4. 超时路径: ThreadPoolExecutor 并发 + per-file ``future.result(timeout=)``
  5. 超时错误消息形如 ``"编译超时 (>Ns)"``
  6. 一个文件 hang 不阻塞其他文件
  7. backward compat: 默认 ``timeout_s=None`` 行为与 v0.5.5 完全一致
  8. ``timeout_s<=0`` 兜底为 None (不触发 ThreadPoolExecutor)

依赖 conftest.repo_root 提供的 tmp 仓库根 (含 .git/)。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from xragent.config.settings import get_settings
from xragent.tools import evolve_tools


# -------------------- fixtures (跨文件可见问题：本文件 inline 定义) --------------------

@pytest.fixture
def evolution_on():
    """显式确保 evolution_enabled=True。"""
    s = get_settings()
    orig = s.evolution_enabled
    object.__setattr__(s, "evolution_enabled", True)
    yield s
    object.__setattr__(s, "evolution_enabled", orig)


@pytest.fixture
def evolution_off():
    """把 evolution_enabled 关掉, 验证门控。"""
    s = get_settings()
    orig = s.evolution_enabled
    object.__setattr__(s, "evolution_enabled", False)
    yield s
    object.__setattr__(s, "evolution_enabled", orig)


def _seed_src(repo_root: Path, files: dict[str, str]) -> Path:
    """在 repo_root/src/ 下写一组 .py 文件 (key=相对路径, value=源码)。"""
    src = repo_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


# -------------------- _compile_one --------------------

class TestCompileOneHelper:
    """抽 helper: 让串行/并发路径共用同一份编译逻辑。"""

    def test_valid_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "ok.py"
        p.write_text("x = 1\n", encoding="utf-8")
        assert evolve_tools._compile_one(p) is None

    def test_syntax_error_returns_nonempty_string(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.py"
        p.write_text("def (\n", encoding="utf-8")
        err = evolve_tools._compile_one(p)
        assert isinstance(err, str)
        assert err  # 非空


# -------------------- 常量 --------------------

class TestConstants:
    def test_compile_timeout_s_positive_int(self) -> None:
        assert isinstance(evolve_tools.COMPILE_TIMEOUT_S, int)
        assert evolve_tools.COMPILE_TIMEOUT_S > 0

    def test_compile_max_workers_positive_int(self) -> None:
        assert isinstance(evolve_tools.COMPILE_MAX_WORKERS, int)
        assert evolve_tools.COMPILE_MAX_WORKERS > 0


# -------------------- backward compat (默认串行) --------------------

class TestCheckCompileBackwardCompat:
    """timeout_s=None (默认) 必须走原串行快路径, 与 v0.5.5 100% 一致。"""

    def test_default_no_timeout_returns_serial_results(
        self, repo_root: Path
    ) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
        results = evolve_tools._check_compile(repo_root)
        assert {r["file"] for r in results} == {"src/a.py", "src/pkg/b.py"}
        assert all(r["ok"] for r in results)

    def test_explicit_none_same_as_default(self, repo_root: Path) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n"})
        a = evolve_tools._check_compile(repo_root)
        b = evolve_tools._check_compile(repo_root, timeout_s=None)
        assert a == b

    def test_zero_timeout_treated_as_none(self, repo_root: Path) -> None:
        """timeout_s=0 兜底为 None — 不触发 ThreadPoolExecutor 立即超时。"""
        _seed_src(repo_root, {"a.py": "x = 1\n", "b.py": "def (\n"})
        results = evolve_tools._check_compile(repo_root, timeout_s=0)
        by_file = {r["file"]: r for r in results}
        assert by_file["src/a.py"]["ok"] is True
        assert by_file["src/b.py"]["ok"] is False  # 仍能识别 syntax error

    def test_negative_timeout_treated_as_none(self, repo_root: Path) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n"})
        results = evolve_tools._check_compile(repo_root, timeout_s=-5)
        assert results[0]["ok"] is True


# -------------------- 超时路径 (并发) --------------------

class TestCheckCompileTimeout:
    """timeout_s=正整数 → 走 ThreadPoolExecutor + per-file timeout。"""

    def test_concurrent_compile_succeeds(self, repo_root: Path) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n", "b.py": "y = 2\n", "c.py": "z = 3\n"})
        results = evolve_tools._check_compile(repo_root, timeout_s=5)
        assert len(results) == 3
        assert all(r["ok"] for r in results)

    def test_concurrent_compile_marks_syntax_error(self, repo_root: Path) -> None:
        _seed_src(
            repo_root,
            {"good.py": "x = 1\n", "bad.py": "def (\n"},
        )
        results = evolve_tools._check_compile(repo_root, timeout_s=5)
        by_file = {r["file"]: r for r in results}
        assert by_file["src/good.py"]["ok"] is True
        assert by_file["src/bad.py"]["ok"] is False
        assert "error" in by_file["src/bad.py"]
        assert by_file["src/bad.py"]["error"]  # 非空

    def test_hang_file_marked_timeout_does_not_block_others(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一个文件 hang 时, 其他文件应正常编译成功, hang 文件标记超时。

        通过 monkeypatch ``_compile_one``: 让 "hang.py" sleep(2), 其他
        文件直接走真实 ``py_compile.compile``。timeout_s=0.3 触发超时,
        但其他两个文件几毫秒就完成。
        """
        _seed_src(
            repo_root,
            {
                "fast1.py": "a = 1\n",
                "hang.py": "h = 1\n",
                "fast2.py": "b = 2\n",
            },
        )

        real_compile_one = evolve_tools._compile_one

        def fake_compile_one(path: Path) -> str | None:
            if path.name == "hang.py":
                time.sleep(2.0)  # 故意 hang, 超过 timeout_s=0.3
                return None
            return real_compile_one(path)

        monkeypatch.setattr(evolve_tools, "_compile_one", fake_compile_one)

        results = evolve_tools._check_compile(
            repo_root, timeout_s=0.3, max_workers=2
        )
        by_file = {r["file"]: r for r in results}

        # 关键断言
        assert by_file["src/fast1.py"]["ok"] is True
        assert by_file["src/fast2.py"]["ok"] is True
        assert by_file["src/hang.py"]["ok"] is False
        # 超时错误消息必须包含 "编译超时" 与 ">0.3"
        assert "编译超时" in by_file["src/hang.py"]["error"]
        assert ">0.3s" in by_file["src/hang.py"]["error"]

    def test_all_files_hang_returns_all_timeouts(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_src(repo_root, {"a.py": "x = 1\n", "b.py": "y = 2\n"})

        def slow_compile_one(path: Path) -> str | None:
            time.sleep(2.0)
            return None

        monkeypatch.setattr(evolve_tools, "_compile_one", slow_compile_one)

        results = evolve_tools._check_compile(
            repo_root, timeout_s=0.2, max_workers=2
        )
        assert len(results) == 2
        for r in results:
            assert r["ok"] is False
            assert "编译超时" in r["error"]

    def test_no_py_files_returns_empty_list(self, repo_root: Path) -> None:
        # src 存在但无 .py
        (repo_root / "src").mkdir(parents=True, exist_ok=True)
        results = evolve_tools._check_compile(repo_root, timeout_s=5)
        assert results == []

    def test_missing_src_dir_returns_empty(self, tmp_path: Path) -> None:
        # 用 fresh tmp_path, 不依赖 conftest
        assert evolve_tools._check_compile(tmp_path, timeout_s=5) == []

    def test_max_workers_kwarg_accepted(self, repo_root: Path) -> None:
        """max_workers 参数必须被接受 (kw-only); 任意正整数都行。"""
        _seed_src(repo_root, {"a.py": "x = 1\n"})
        results = evolve_tools._check_compile(
            repo_root, timeout_s=5, max_workers=1
        )
        assert len(results) == 1


# -------------------- 与 LLM 工具契约协同 --------------------

class TestProposeSelfReplaceWithTimeout:
    """dry_run=True 的 ``propose_self_replace`` 走 ``_check_compile``。

    这里只验证契约键集不变 (timeout 不影响 LLM-facing 工具键集合)。
    """

    def test_dry_run_keys_unchanged(
        self, repo_root: Path, evolution_on
    ) -> None:
        from xragent.tools.evolve_tools import propose_self_replace
        _seed_src(repo_root, {"a.py": "x = 1\n"})
        r = propose_self_replace("trial", dry_run=True)
        assert set(r.keys()) == {"ok", "compile_results", "dry_run", "head_after"}

    def test_evolution_disabled_unchanged(
        self, repo_root: Path, evolution_off
    ) -> None:
        from xragent.tools.evolve_tools import propose_self_replace
        r = propose_self_replace("trial", dry_run=True)
        assert r == {"ok": False, "blocked_by": "evolution_disabled"}