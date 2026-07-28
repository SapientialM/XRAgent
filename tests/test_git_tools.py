"""git_tools.git_commit / git_tools.git_push：包装层边界条件。

背景：src/xragent/snapshot/side_git.py 的 SideGit 已有 test_sidegit.py 覆盖
（snapshot / tag / stash 排除 / push no remote 等）。但 src/xragent/tools/git_tools.py
是 Agent 直接调用的包装层（risk='high'），它的返回结构是 LLM 工具契约的一部分，
先前完全没测。本文件锁定 *当前* 实现的关键契约：

git_commit(message) → dict
    - 无改动 → ok=True, head=None, no_changes=True（这是关键的"幂等"语义：
      两次相同 commit 调用不会让 HEAD 漂移、不会污染日志）
    - 有改动 → ok=True, head=<sha>, no_changes=False，sha 长度 ≥ 7
    - message 含空格 / 特殊字符 / 中文 / emoji 都能走通（透传到底层 git）
    - 多次连续 commit：第二次在无改动时仍返回 no_changes=True
      （不能因为 SideGit 实例缓存而漏判）

git_push(remote, branch) → dict
    - 无 origin 时：ok=False, msg 是非空字符串（含 stderr）
    - 默认参数是 ("origin", "main")，与 SideGit.push 默认一致
    - 自定义 remote/branch 被正确透传到底层 git push
    - ok 一定是 bool、msg 一定是 str（LLM 解析契约）
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from xragent.tools import git_tools


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------


def test_git_commit_no_changes_returns_no_changes_true(repo_root: Path):
    """干净仓库下 git_commit → no_changes=True, head=None。

    这是 Agent 调用 "git_commit('noop')" 时最常见的情形：没文件改动。
    必须明确告诉上层"什么都没发生"，而不是假装成功提交。
    """
    r = git_tools.git_commit("noop")
    assert r["ok"] is True
    assert r["no_changes"] is True
    assert r["head"] is None


def test_git_commit_with_changes_returns_head_sha(repo_root: Path):
    """有改动时 → head 是合法 sha, no_changes=False。"""
    (repo_root / "sandbox" / "commit_target.txt").write_text(
        "hello", encoding="utf-8"
    )
    r = git_tools.git_commit("add commit_target")
    assert r["ok"] is True
    assert r["no_changes"] is False
    assert isinstance(r["head"], str)
    # git 短 hash 标准是 7+ 字符（hex）；如果实现截断了长度会立刻露馅
    assert len(r["head"]) >= 7
    assert all(c in "0123456789abcdef" for c in r["head"]), (
        f"head 不是 hex sha: {r['head']!r}"
    )


def test_git_commit_message_with_whitespace_and_special_chars(repo_root: Path):
    """commit message 含空格 / 冒号 / 括号 → 仍能成功。

    实现直接透传给 `git commit -m <message>`，没做引号转义 —— shell=True 的
    git 进程会处理。锁定当前行为，避免后续重构引入 quoting bug。
    """
    (repo_root / "sandbox" / "msg.txt").write_text("x", encoding="utf-8")
    msg = "feat: add msg.txt (with brackets) and !@#$"
    r = git_tools.git_commit(msg)
    assert r["ok"] is True
    assert r["no_changes"] is False
    assert r["head"] is not None

    # 落盘的 commit message 必须是原文（含冒号、括号、特殊字符）
    head = r["head"]
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s", head],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert log.returncode == 0
    assert log.stdout.strip() == msg, (
        f"message 透传失真：got {log.stdout.strip()!r}, expected {msg!r}"
    )


def test_git_commit_message_unicode_and_emoji(repo_root: Path):
    """commit message 含中文 / emoji → 落盘正确（utf-8）。"""
    (repo_root / "sandbox" / "u.txt").write_text("y", encoding="utf-8")
    msg = "测试：边界 🌱 git_commit"
    r = git_tools.git_commit(msg)
    assert r["ok"] is True
    assert r["head"] is not None

    head = r["head"]
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s", head],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert log.stdout.strip() == msg


def test_git_commit_consecutive_no_op_calls_stay_idempotent(repo_root: Path):
    """连续多次无改动 commit → 都返回 no_changes=True，不能让 HEAD 漂移。"""
    r1 = git_tools.git_commit("noop-1")
    r2 = git_tools.git_commit("noop-2")
    r3 = git_tools.git_commit("noop-3")
    assert all(r["ok"] is True for r in (r1, r2, r3))
    assert all(r["no_changes"] is True for r in (r1, r2, r3))
    assert all(r["head"] is None for r in (r1, r2, r3))

    # 落盘的 HEAD 应当仍是初始 commit（没有新增）
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.strip()
    init_head = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == init_head, (
        f"连续 no-op commit 不应推进 HEAD: current={head}, init={init_head}"
    )


def test_git_commit_after_change_then_no_change_transitions_correctly(repo_root: Path):
    """状态机语义：先有改动 → no_changes=False；接着再 commit（无新改动）→ no_changes=True。

    这条锁的是 *SideGit 实例在两次调用之间重新读取 git status* 的行为，
    而不是缓存上一次的状态。
    """
    # 1) 有改动
    (repo_root / "sandbox" / "transition.txt").write_text("v1", encoding="utf-8")
    r1 = git_tools.git_commit("first")
    assert r1["no_changes"] is False
    assert r1["head"] is not None

    # 2) 紧接着再 commit（此时无新改动）
    r2 = git_tools.git_commit("second-immediately")
    assert r2["no_changes"] is True
    assert r2["head"] is None

    # 3) 再制造一次改动 → 再次变为 no_changes=False
    (repo_root / "sandbox" / "transition.txt").write_text("v2", encoding="utf-8")
    r3 = git_tools.git_commit("third")
    assert r3["no_changes"] is False
    assert r3["head"] is not None
    # 第三次 commit 的 HEAD 必须不等于第一次（线性前进）
    assert r3["head"] != r1["head"]


def test_git_commit_return_dict_has_exactly_expected_keys(repo_root: Path):
    """LLM 工具契约：返回值键必须是 {ok, head, no_changes}，不多不少。

    多一个键 / 少一个键都可能让 LLM 的 JSON 解析器走错分支。
    """
    (repo_root / "sandbox" / "keys.txt").write_text("z", encoding="utf-8")
    r = git_tools.git_commit("schema-check")
    assert set(r.keys()) == {"ok", "head", "no_changes"}, (
        f"返回键集合漂移: {sorted(r.keys())}"
    )

    r_no = git_tools.git_commit("noop-keys")
    assert set(r_no.keys()) == {"ok", "head", "no_changes"}


# ---------------------------------------------------------------------------
# git_push
# ---------------------------------------------------------------------------


def test_git_push_no_remote_returns_ok_false_with_message(repo_root: Path):
    """conftest 初始化的是裸本地仓库（无 origin）→ push 应失败。"""
    r = git_tools.git_push()
    assert r["ok"] is False
    assert isinstance(r["msg"], str)
    assert r["msg"], "失败时 msg 必须非空，便于 LLM 看到诊断信息"


def test_git_push_returns_bool_and_str_contract(repo_root: Path):
    """LLM 契约：ok 是 bool、msg 是 str —— 即使后续重构也不要换类型。"""
    r = git_tools.git_push()
    assert isinstance(r["ok"], bool)
    assert isinstance(r["msg"], str)
    # 必须恰好两个键
    assert set(r.keys()) == {"ok", "msg"}


def test_git_push_custom_remote_branch_passed_through(repo_root: Path):
    """自定义 remote/branch 必须透传到底层 `git push <remote> <branch>`。

    通过 monkeypatch subprocess.run 捕获调用参数，验证参数确实传过去了。
    不需要真的成功（也没远程），只看参数。
    """
    from xragent.snapshot import side_git

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        # 模拟一个失败但返回结构完整的 CompletedProcess
        cp = subprocess.CompletedProcess(args=args, returncode=128, stderr="fake", stdout="")
        return cp

    monkey = pytest.MonkeyPatch()
    monkey.setattr(side_git.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push(remote="myfork", branch="dev-branch")
    finally:
        monkey.undo()

    assert captured["args"][:3] == ["git", "push", "myfork"]
    assert "dev-branch" in captured["args"], (
        f"branch 未透传：args={captured['args']}"
    )
    assert r["ok"] is False  # 我们伪造 returncode=128
    assert "fake" in r["msg"]


def test_git_push_default_remote_branch_is_origin_main(repo_root: Path):
    """默认参数必须是 ('origin', 'main')，与 SideGit.push 签名一致。"""
    from xragent.snapshot import side_git

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(side_git.subprocess, "run", fake_run)
    try:
        r = git_tools.git_push()
    finally:
        monkey.undo()

    assert captured["args"] == ["git", "push", "origin", "main"], (
        f"默认参数漂移：{captured['args']}"
    )
    # 我们伪造 returncode=0，所以应当报成功
    assert r["ok"] is True
    assert r["msg"] == ""


# ---------------------------------------------------------------------------
# 跨模块交叉：git_commit + git_push 的串联（薄烟雾测试）
# ---------------------------------------------------------------------------


def test_git_commit_then_push_chain_does_not_raise(repo_root: Path):
    """最小烟雾：commit + push 串联调用不能因为 SideGit 实例状态污染而崩。"""
    (repo_root / "sandbox" / "chain.txt").write_text("c", encoding="utf-8")
    cr = git_tools.git_commit("chain: add chain.txt")
    assert cr["ok"] is True
    assert cr["no_changes"] is False
    assert cr["head"] is not None

    pr = git_tools.git_push()
    assert isinstance(pr["ok"], bool)
    # 没有 origin → 失败，但函数不能崩
    assert pr["ok"] is False
    assert isinstance(pr["msg"], str)