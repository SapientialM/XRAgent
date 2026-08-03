"""tests/test_evolve_tools_robustness.py

锁定 evolve_tools 的鲁棒性增强 (round 381+):
  1. _check_compile 在 src_dir.rglob 抛 OSError 时返回单条 error entry
     (而不是空 list → dry_run 误报 ok).
  2. propose_self_replace 正常路径下 metamorphose 抛 OSError / RuntimeError
     时返回结构化 _io_fail 形态 {"ok": False, "error": ...}, 不上抛 traceback.
  3. terminate 在 _save_runtime_state 抛 OSError 时仍发 SIGTERM + 落
     lifecycle memory fact, 写盘失败原因打到 stderr (测试 monkeypatch sys.stderr
     不污染真实 stderr).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pytest

from xragent.tools import evolve_tools


# -------------------- fixtures --------------------

@pytest.fixture
def stderr_capture(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """把 sys.stderr 替换成 StringIO, 让 terminate 写盘失败的告警可断言."""
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    return buf


def _seed_src(repo_root: Path, files: dict[str, str]) -> Path:
    """在 repo_root/src/ 下写一组 .py 文件 (key=相对路径, value=源码)."""
    src = repo_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


# -------------------- 1. _check_compile rglob OSError --------------------

class TestCheckCompileRglobOSError:
    def test_rglob_oserror_returns_error_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 造一个 src/ 目录, 让 rglob 抛 OSError (PermissionError / 损坏 symlink
        # 都是 OSError 子类).
        src = tmp_path / "src"
        src.mkdir()

        def boom_rglob(self: Path, pattern: str) -> Any:  # noqa: ARG001
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "rglob", boom_rglob)

        results = evolve_tools._check_compile(tmp_path)
        assert len(results) == 1
        entry = results[0]
        assert entry["ok"] is False
        assert entry["file"] == "src/"
        # 文案契约: "<prefix>: <type_name>: <msg>"
        assert "PermissionError" in entry["error"]
        assert "Permission denied" in entry["error"]

    def test_rglob_oserror_propagates_to_dry_run_ok_false(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        # dry_run 路径消费 _check_compile: 出错时 ok 必须 False, 不能 silent skip.
        (repo_root / "src").mkdir()

        def boom_rglob(self: Path, pattern: str) -> Any:  # noqa: ARG001
            raise OSError(5, "I/O error")

        monkeypatch.setattr(Path, "rglob", boom_rglob)

        r = evolve_tools.propose_self_replace("trial", dry_run=True)
        assert r["ok"] is False
        assert r["dry_run"] is True
        assert len(r["compile_results"]) == 1
        assert r["compile_results"][0]["ok"] is False

    def test_rglob_oserror_does_not_break_existing_ok_files(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        # 边界: rglob 自身抛 → 没机会跑到 py_compile; 不会因为这次失败
        # 把已经 OK 的文件"染色"成 ok=False.
        _seed_src(repo_root, {"a.py": "x = 1\n"})

        def boom_rglob(self: Path, pattern: str) -> Any:  # noqa: ARG001
            raise FileNotFoundError(2, "No such file")

        monkeypatch.setattr(Path, "rglob", boom_rglob)

        results = evolve_tools._check_compile(repo_root)
        # 仍是一条 error entry, 没有 a.py
        assert len(results) == 1
        assert results[0]["ok"] is False


# -------------------- 2. propose_self_replace normal-path 异常兜底 --------------------

class TestProposeSelfReplaceErrorTrap:
    def test_metamorphose_oserror_returns_io_fail_shape(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        def fake_metamorphose(**_kw: Any) -> dict[str, Any]:
            raise PermissionError(13, "Permission denied", "/dev/null")

        monkeypatch.setattr(evolve_tools, "metamorphose", fake_metamorphose)

        r = evolve_tools.propose_self_replace("trial")
        # 结构化错误, 不是 traceback
        assert set(r.keys()) == {"ok", "error"}
        assert r["ok"] is False
        assert "metamorphose 失败" in r["error"]
        assert "PermissionError" in r["error"]
        assert "Permission denied" in r["error"]

    def test_metamorphose_runtimeerror_from_sidegit_returns_io_fail_shape(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        # SideGit._run 把 git 失败 raise RuntimeError — 这是真生产场景.
        def fake_metamorphose(**_kw: Any) -> dict[str, Any]:
            raise RuntimeError("git binary not found")

        monkeypatch.setattr(evolve_tools, "metamorphose", fake_metamorphose)

        r = evolve_tools.propose_self_replace("trial")
        assert r["ok"] is False
        assert "metamorphose 失败" in r["error"]
        assert "RuntimeError" in r["error"]
        assert "git binary not found" in r["error"]

    def test_metamorphose_typeerror_still_propagates(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        # 编程错误不吞: TypeError / KeyError 等仍应上抛, 让上层抓到.
        def fake_metamorphose(**_kw: Any) -> dict[str, Any]:
            raise TypeError("bad arg shape")

        monkeypatch.setattr(evolve_tools, "metamorphose", fake_metamorphose)

        with pytest.raises(TypeError, match="bad arg shape"):
            evolve_tools.propose_self_replace("trial")

    def test_normal_path_success_unaffected(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, evolution_on
    ) -> None:
        # 反向用例: 正常路径成功时, 返回仍是 metamorphose 原 dict, 没被兜底吞掉.
        monkeypatch.setattr(
            evolve_tools, "metamorphose",
            lambda **_kw: {"ok": True, "head_after": "abc123"},
        )

        r = evolve_tools.propose_self_replace("trial")
        assert r == {"ok": True, "head_after": "abc123"}


# -------------------- 3. terminate 写盘失败仍 SIGTERM --------------------

class TestTerminateStateWriteFails:
    def test_save_state_oserror_still_fires_sigterm(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch,
        evolution_on, no_kill, stderr_capture: io.StringIO,
    ) -> None:
        def fake_save(path: Path, state: dict[str, Any]) -> None:
            raise PermissionError(13, "Read-only fs", str(path))

        monkeypatch.setattr(evolve_tools, "_save_runtime_state", fake_save)

        r = evolve_tools.terminate("写盘炸了")

        # 返回值仍是结构化 ok=True
        assert r == {"ok": True, "reason": "写盘炸了"}
        # SIGTERM 仍发 (关键!)
        assert len(no_kill) == 1
        assert no_kill[0][1] == 15
        # stderr 留痕, supervisor / 运维能看到失败原因
        err_output = stderr_capture.getvalue()
        assert "runtime_state 写盘失败" in err_output
        assert "PermissionError" in err_output
        assert "写盘炸了" in err_output  # reason 也带上方便定位

    def test_save_state_oserror_still_logs_lifecycle_memory(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch,
        evolution_on, no_kill, stderr_capture: io.StringIO,  # noqa: ARG002
    ) -> None:
        from xragent.memory.manager import MemoryManager

        def fake_save(path: Path, state: dict[str, Any]) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(evolve_tools, "_save_runtime_state", fake_save)

        m = MemoryManager()
        before = len(m.recall_range(category="lifecycle"))

        evolve_tools.terminate("盘满了")

        after = len(m.recall_range(category="lifecycle"))
        assert after == before + 1  # lifecycle fact 仍落
        # SIGTERM 也仍发
        assert len(no_kill) == 1

    def test_save_state_success_no_stderr_warning(
        self, repo_root: Path, evolution_on, no_kill,
        stderr_capture: io.StringIO,  # noqa: ARG002
    ) -> None:
        # 反向用例: 写盘正常时, stderr 没多打失败告警.
        evolve_tools.terminate("正常")
        assert "runtime_state 写盘失败" not in stderr_capture.getvalue()