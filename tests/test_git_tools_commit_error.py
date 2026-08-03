"""git_tools.git_commit 异常兜底契约（v0.5.6）。

为什么独立文件: 与 test_git_tools.py 的"成功路径契约锁"分离。
本文件只覆盖 *异常路径*: 当底层 SideGit / subprocess 抛错时,
git_commit 必须返回 dict (不能冒泡), 且结构满足:

  - 严格 4 键: ``{ok, head, no_changes, error}``
  - ``ok`` = False (与"无改动"路径的 ok=True 区分开)
  - ``head`` = None (恒定)
  - ``no_changes`` = False (与"无改动"路径的 no_changes=True 区分开 —— 防止 LLM
    把"git 仓库坏了"误判成"没有文件改动")
  - ``error`` 是非空 str, 含 ``<异常类名>: <str(e)>``, 便于诊断

为什么用 monkeypatch 而非真坏 .git/: 测试要快 + 不污染 repo_root fixture。
SideGit 是 git_tools.py 里 ``sg = SideGit()`` 拿到的实例,
``sg.add_all_and_commit`` 是方法; 我们 monkeypatch SideGit 类方法,
让所有 SideGit 实例的 add_all_and_commit 都抛错。

清理: 每个测试都用 ``monkeypatch`` fixture, pytest 自动 undo,
不会污染其它测试文件里的 git_commit 调用。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xragent.snapshot import side_git
from xragent.tools import git_tools


def _patch_add_all_and_commit(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """monkeypatch SideGit.add_all_and_commit → 抛 exc。"""
    def boom(self, message, min_diff_bytes=100):  # noqa: ARG001
        raise exc

    monkeypatch.setattr(side_git.SideGit, "add_all_and_commit", boom)


# ===========================================================================
# RuntimeError (SideGit 内部 git_helpers.git_run 抛 —— 最常见的真实失败)
# ===========================================================================


def test_git_commit_runtime_error_returns_ok_false_with_diagnostic(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
):
    """.git/ 损坏 → SideGit._run 抛 RuntimeError → 工具层兜底返回 dict。

    RuntimeError 是 SideGit 失败时最常见的异常 (git_helpers.git_run 在
    rc != 0 时 raise RuntimeError(f"git ... 失败: ..."))。这是兜底契约
    的核心场景。
    """
    _patch_add_all_and_commit(
        monkeypatch,
        RuntimeError("git rev-parse HEAD failed: not a git repository"),
    )
    r = git_tools.git_commit("test")
    assert r["ok"] is False
    assert r["head"] is None
    assert r["no_changes"] is False
    assert isinstance(r["error"], str)
    assert r["error"], "错误路径 error 必须非空"
    assert "RuntimeError" in r["error"]
    assert "not a git repository" in r["error"]


# ===========================================================================
# FileNotFoundError (git 二进制缺失 / subprocess 启动失败)
# ===========================================================================


def test_git_commit_file_not_found_returns_ok_false(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
):
    """git binary 不在 PATH → SideGit 抛 FileNotFoundError → 兜底。"""
    _patch_add_all_and_commit(
        monkeypatch,
        FileNotFoundError(2, "No such file or directory", "git"),
    )
    r = git_tools.git_commit("test")
    assert r["ok"] is False
    assert r["head"] is None
    assert r["no_changes"] is False
    assert "FileNotFoundError" in r["error"]


# ===========================================================================
# OSError (磁盘满 / IO 错误)
# ===========================================================================


def test_git_commit_os_error_returns_ok_false(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
):
    """磁盘 IO 错 → 兜底返回 ok=False, 不冒泡。"""
    _patch_add_all_and_commit(
        monkeypatch,
        OSError(28, "No space left on device"),
    )
    r = git_tools.git_commit("test")
    assert r["ok"] is False
    assert r["head"] is None
    assert r["no_changes"] is False
    assert "OSError" in r["error"]
    assert "No space left" in r["error"]


# ===========================================================================
# 键集合契约: 错误路径必须严格 4 键
# ===========================================================================


def test_git_commit_error_path_has_exactly_four_keys(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
):
    """错误路径键集合 = {ok, head, no_changes, error}, 严格不多不少。

    这是 LLM 工具契约的一部分 —— 加 key / 少 key 都会让 prompt 模板里的
    ``r["error"]`` / ``r["head"]`` 解析漂移。
    """
    _patch_add_all_and_commit(monkeypatch, RuntimeError("boom"))
    r = git_tools.git_commit("x")
    assert set(r.keys()) == {"ok", "head", "no_changes", "error"}, (
        f"错误路径键集合漂移: {sorted(r.keys())}"
    )


# ===========================================================================
# 异常路径不应冒泡到 LLM 调用方
# ===========================================================================


def test_git_commit_does_not_raise_on_sidegit_failure(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
):
    """核心契约: SideGit 抛 RuntimeError 时, git_commit 自身绝不抛异常。

    之前的实现直接调 SideGit().add_all_and_commit(), .git 损坏时会冒泡
    RuntimeError 把 LLM 工具调用打挂 —— 这是 v0.5.6 修复的 bug。
    """
    _patch_add_all_and_commit(
        monkeypatch,
        RuntimeError("fatal: not a git repository"),
    )
    try:
        r = git_tools.git_commit("x")
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"git_commit 不应冒泡异常, 但抛了: {type(e).__name__}: {e}")
    assert r["ok"] is False