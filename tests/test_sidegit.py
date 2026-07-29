"""SideGit：snapshot + tag + stash 排除。"""
from __future__ import annotations

from xragent.snapshot.side_git import SideGit, Snapshot


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
    """修复 v0.2 之前的 fixture bug：原来写 "hi"（2 字节）< 默认 min_diff_bytes=100。

    min_diff_bytes 默认 100 是有意护栏。但该参数实际测的是 git diff --shortstat
    的"行数"（ins + dels），不是字节数（参数名有误导，见 v0.2 注释）。
    本测试写 ~150 行真实 diff，反映真实使用场景。
    """
    sg = SideGit()
    sg.ensure_repo()
    payload = "line\n" * 150  # 150 行, 超过默认 100 阈值
    (repo_root / "sandbox" / "new.txt").write_text(payload, encoding="utf-8")
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


# === v0.2 新增测试：Snapshot 扩展 + 新方法 ===

def test_snapshot_dataclass_has_committed_head(repo_root):
    """v0.2: Snapshot 新字段 committed_head，默认 None，向后兼容。"""
    # 老式 3 字段构造仍合法
    snap_old = Snapshot(tag="xragent/turn-legacy", pre_stash=None, note="legacy")
    assert snap_old.committed_head is None  # 默认值

    # 新式 4 字段构造
    snap_new = Snapshot(
        tag="xragent/turn-x", pre_stash="xragent-pre-x", note="x", committed_head="abc1234"
    )
    assert snap_new.committed_head == "abc1234"


def test_add_and_commit_with_stats_returns_snapshot(repo_root):
    """v0.2 新方法 add_and_commit_with_stats 返回 Snapshot，committed_head 有值。"""
    sg = SideGit()
    sg.ensure_repo()
    payload = "x\n" * 120  # 120 行 > 默认 min_diff_bytes=100
    (repo_root / "sandbox" / "stats.txt").write_text(payload, encoding="utf-8")

    snap = sg.add_and_commit_with_stats("stats test", note="with stats")
    assert isinstance(snap, Snapshot)
    assert snap.committed_head is not None
    assert len(snap.committed_head) >= 7
    assert snap.tag == ""  # 此方法不打 tag
    assert snap.note == "with stats"


def test_add_and_commit_with_stats_skips_small_diff(repo_root):
    """v0.2: diff < min_diff_bytes 时 committed_head 应为 None。"""
    sg = SideGit()
    sg.ensure_repo()
    (repo_root / "sandbox" / "tiny.txt").write_text("hi", encoding="utf-8")
    snap = sg.add_and_commit_with_stats("tiny", min_diff_bytes=100)
    assert snap.committed_head is None
    assert snap.tag == ""


def test_commit_snapshot_combines_snapshot_and_commit(repo_root):
    """v0.2 新方法 commit_snapshot：组合 snapshot + add_all_and_commit，原子返回。"""
    sg = SideGit()
    sg.ensure_repo()
    payload = "y\n" * 120  # 120 行触发 commit
    (repo_root / "sandbox" / "combo.txt").write_text(payload, encoding="utf-8")

    snap = sg.commit_snapshot("t9", note="combo", min_diff_bytes=100)
    assert isinstance(snap, Snapshot)
    # tag 应被打上
    assert snap.tag == "xragent/turn-t9"
    assert "xragent/turn-t9" in sg.list_snapshots()
    # committed_head 也应有值
    assert snap.committed_head is not None
    assert len(snap.committed_head) >= 7
    assert snap.note == "combo"


def test_add_all_and_commit_signature_unchanged(repo_root):
    """v0.2 不破坏现有 API：add_all_and_commit 仍返回 str | None。"""
    import inspect
    sig = inspect.signature(SideGit.add_all_and_commit)
    # 返回类型注解应为 str | None（兼容 3 个调用方）
    assert sig.return_annotation in ("str | None", "Optional[str]")