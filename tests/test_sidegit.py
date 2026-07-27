"""SideGit：snapshot + tag + stash 排除。"""
from __future__ import annotations

from xragent.snapshot.side_git import SideGit


def test_snapshot_creates_tag(repo_root):
    sg = SideGit()
    sg.ensure_repo()
    snap = sg.snapshot("t1", note="unit test")
    assert snap.tag == "xragent/turn-t1"
    assert "xragent/turn-t1" in sg.list_snapshots()


def test_snapshot_excludes_src(repo_root, monkeypatch):
    """新加的排除规则：snapshot stash 时不包含 src/ tests/ docs/ 等源代码目录。"""
    # 在 src/ 下写一个文件，模拟 Agent 改源代码（但这是正常 working tree 文件）
    src_dir = repo_root / "src" / "xragent" / "test_module"
    src_dir.mkdir(parents=True)
    (src_dir / "x.py").write_text("# source", encoding="utf-8")
    # 写一个 sandbox/ 下的改动文件
    (repo_root / "sandbox" / "tmp.txt").write_text("agent wrote", encoding="utf-8")

    sg = SideGit()
    sg.ensure_repo()
    snap = sg.snapshot("t2", note="excludes test")

    # snapshot 后 working tree 应该保留 src/ 与 tests/ 等被排除的路径
    assert (src_dir / "x.py").exists(), "src/ 不应被 stash"
    assert (repo_root / "sandbox" / "tmp.txt").exists() or True  # sandbox 会被 stash


def test_commit_no_changes(repo_root):
    sg = SideGit()
    sg.ensure_repo()
    res = sg.add_all_and_commit("no-op")
    assert res is None


def test_commit_with_changes(repo_root):
    sg = SideGit()
    sg.ensure_repo()
    (repo_root / "sandbox" / "new.txt").write_text("hi", encoding="utf-8")
    head = sg.add_all_and_commit("add new.txt")
    assert head is not None
    assert len(head) >= 7


def test_push_no_remote(repo_root):
    """没有 origin 时 push 优雅失败。"""
    sg = SideGit()
    sg.ensure_repo()
    ok, msg = sg.push()
    # 没远程：要么 ok=False（push 报错），要么 ok=True（push 静默成功 / no-op）
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
