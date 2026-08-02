"""``snapshot.count_cleanup.cleanup_old_snapshots_by_count`` 行为契约。

与 ``test_sidegit_cleanup.py`` 同源风格：``repo_root`` fixture 起真 git
repo，``_make_annotated_tag`` 用 ``GIT_COMMITTER_DATE`` 倒拨 creatordate
来控制"新旧"——无需 monkeypatch 真实时钟。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from xragent.snapshot.count_cleanup import cleanup_old_snapshots_by_count
from xragent.snapshot.side_git import SideGit


def _make_annotated_tag(repo: str, tag: str, message: str, unix_ts: int) -> None:
    """把 annotated tag 的 creatordate 强制写为 ``unix_ts``。

    annotated tag (``-m``) 才会写 creatordate；git 在创建 tag 时读
    ``GIT_COMMITTER_DATE`` / ``GIT_AUTHOR_DATE``。这是测试里"模拟 N 天
    前的 tag"的最干净方式，无需 monkeypatch 真实时钟。
    """
    env = os.environ.copy()
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(unix_ts))
    env["GIT_COMMITTER_DATE"] = iso
    env["GIT_AUTHOR_DATE"] = iso
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", message],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_count_cleanup_disabled_when_max_count_zero(repo_root):
    """``max_count <= 0`` → 禁用清理：直接返回 ``[]``，不动任何 tag。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-a", "a", now - 100 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-b", "b", now - 200 * 86400)

    for v in (0, -1, -10):
        assert cleanup_old_snapshots_by_count(sg, max_count=v) == []
        assert cleanup_old_snapshots_by_count(sg, max_count=v, dry_run=True) == []
        # tag 仍在
        assert "xragent/turn-a" in sg.list_snapshots()
        assert "xragent/turn-b" in sg.list_snapshots()


def test_count_cleanup_keeps_newest_N_removes_older(repo_root):
    """5 个 tag + max_count=3 → 删 2 个最旧的（按 creatordate）。"""
    sg = SideGit()
    sg.ensure_repo()

    base = int(time.time())
    # 显式间隔 1 天，保证 creatordate 单调递增（annotated tag 同秒打会平序，
    # 而排序稳定性依赖 creatordate 严格递增以避免歧义）。
    tags_with_ts = [
        ("xragent/turn-1", base - 50 * 86400),  # 最旧 → 删
        ("xragent/turn-2", base - 40 * 86400),  # 删
        ("xragent/turn-3", base - 30 * 86400),  # 保留
        ("xragent/turn-4", base - 20 * 86400),  # 保留
        ("xragent/turn-5", base - 10 * 86400),  # 最新 → 保留
    ]
    for name, ts in tags_with_ts:
        _make_annotated_tag(str(repo_root), name, name, ts)

    removed = cleanup_old_snapshots_by_count(sg, max_count=3)

    # 按 creatordate 旧→新：turn-1, turn-2
    assert removed == ["xragent/turn-1", "xragent/turn-2"]
    # list_snapshots 内部已 --sort=-creatordate（新→旧）
    assert sg.list_snapshots() == [
        "xragent/turn-5",
        "xragent/turn-4",
        "xragent/turn-3",
    ]


def test_count_cleanup_noop_when_under_limit(repo_root):
    """tag 数量 ≤ max_count → 返回 ``[]``，原列表不动。"""
    sg = SideGit()
    sg.ensure_repo()

    base = int(time.time())
    for name, ts in [
        ("xragent/turn-a", base - 10 * 86400),
        ("xragent/turn-b", base - 20 * 86400),
    ]:
        _make_annotated_tag(str(repo_root), name, name, ts)

    before = sg.list_snapshots()
    assert cleanup_old_snapshots_by_count(sg, max_count=10) == []
    assert sg.list_snapshots() == before


def test_count_cleanup_dry_run_lists_but_does_not_delete(repo_root):
    """``dry_run=True`` 只列候选，不执行 ``git tag -d``。"""
    sg = SideGit()
    sg.ensure_repo()

    base = int(time.time())
    for name, ts in [
        ("xragent/turn-old1", base - 50 * 86400),
        ("xragent/turn-old2", base - 40 * 86400),
        ("xragent/turn-new",  base - 5  * 86400),
    ]:
        _make_annotated_tag(str(repo_root), name, name, ts)

    listed = cleanup_old_snapshots_by_count(sg, max_count=1, dry_run=True)

    # 旧→新：old1, old2；new 应保留
    assert listed == ["xragent/turn-old1", "xragent/turn-old2"]
    # dry_run 不应删任何 tag
    assert set(sg.list_snapshots()) == {
        "xragent/turn-old1",
        "xragent/turn-old2",
        "xragent/turn-new",
    }


def test_count_cleanup_ignores_non_xragent_tags(repo_root):
    """非 ``xragent/turn-*`` 前缀的 tag 不应被误删。

    用户手工打的 ``v0.1`` / ``baseline`` 等里程碑 tag 必须保留。
    """
    sg = SideGit()
    sg.ensure_repo()

    base = int(time.time())
    # 用户手工 tag（即使 creatordate 更旧，也不应被数量清理动）
    _make_annotated_tag(str(repo_root), "v0.1", "user", base - 100 * 86400)
    _make_annotated_tag(str(repo_root), "baseline", "user", base - 200 * 86400)
    # 自动前缀 tag：5 个
    for i, days_ago in enumerate([50, 40, 30, 20, 10], start=1):
        _make_annotated_tag(
            str(repo_root),
            f"xragent/turn-{i}",
            f"auto {i}",
            base - days_ago * 86400,
        )

    removed = cleanup_old_snapshots_by_count(sg, max_count=2)

    # 只删了自动前缀中最旧的 3 个，旧→新：turn-1, turn-2, turn-3
    assert removed == ["xragent/turn-1", "xragent/turn-2", "xragent/turn-3"]

    # 直接 git tag -l 验证 user tag 仍在（不只信 list_snapshots）
    all_tags = subprocess.run(
        ["git", "tag", "-l"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "v0.1" in all_tags
    assert "baseline" in all_tags
    # 自动前缀剩 2 个（git tag -l 默认字典序升序）
    auto_tags = sorted(t for t in all_tags if t.startswith("xragent/turn-"))
    assert auto_tags == ["xragent/turn-4", "xragent/turn-5"]


def test_count_cleanup_not_a_repo_is_noop(repo_root):
    """非 git 仓库时静默返回 ``[]``，不抛 —— watchdog/cron 调用不应炸流程。

    用 ``repo_root`` fixture 起一个仓库，删掉 ``.git`` 后再调 cleanup，
    验证 ``is_repo()`` 失败路径走通、且不抛异常。
    """
    shutil.rmtree(repo_root / ".git")
    sg = SideGit()
    assert sg.is_repo() is False
    assert cleanup_old_snapshots_by_count(sg, max_count=10) == []
    assert cleanup_old_snapshots_by_count(sg, max_count=10, dry_run=True) == []


def test_count_cleanup_empty_repo_is_noop(repo_root):
    """合法 git 仓库但没有任何 ``xragent/turn-*`` tag → 返回 ``[]``。

    ``git for-each-ref refs/tags/xragent/turn-*`` 在无匹配时 exit 1，本模块
    必须静默吞下并返回空列表，而不是让调用方炸 RuntimeError。
    """
    sg = SideGit()
    sg.ensure_repo()
    # 仓库里没有任何 xragent/turn-* tag —— 验证 for-each-ref exit 1 路径走通
    assert sg.list_snapshots() == []
    assert cleanup_old_snapshots_by_count(sg, max_count=5) == []
    assert cleanup_old_snapshots_by_count(sg, max_count=5, dry_run=True) == []