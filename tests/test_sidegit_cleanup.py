"""SideGit：cleanup_old_snapshots 行为契约。"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from xragent.snapshot.side_git import SideGit


def _make_annotated_tag(repo: str, tag: str, message: str, unix_ts: int) -> None:
    """用 GIT_COMMITTER_DATE / GIT_AUTHOR_DATE 把 tag 的 creatordate 倒拨到 unix_ts。

    annotated tag (-m) 才会写 creatordate，且 git 在创建 tag 时读这两个
    环境变量，所以这是测试里 "模拟 N 天前的 tag" 的最干净方式，无需
    monkeypatch 真实时钟。
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


def test_cleanup_old_snapshots_removes_only_old_tags(repo_root):
    """31 天前的 tag 应被删；7 天前的应保留。

    用 GIT_COMMITTER_DATE 倒拨 creatordate，无需 monkeypatch 时钟。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    old_ts = now - 31 * 86400   # 31 天前
    fresh_ts = now - 7 * 86400  # 7 天前
    _make_annotated_tag(str(repo_root), "xragent/turn-old", "old snap", old_ts)
    _make_annotated_tag(str(repo_root), "xragent/turn-fresh", "fresh snap", fresh_ts)

    removed = sg.cleanup_old_snapshots(max_age_days=30)
    assert "xragent/turn-old" in removed
    assert "xragent/turn-fresh" not in removed
    # 实际 tag 列表也应只剩 fresh
    assert sg.list_snapshots() == ["xragent/turn-fresh"]


def test_cleanup_old_snapshots_dry_run_does_not_delete(repo_root):
    """dry_run=True 只列出要删的 tag，不执行 `git tag -d`。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-stale", "stale", now - 40 * 86400)

    listed = sg.cleanup_old_snapshots(max_age_days=30, dry_run=True)
    assert listed == ["xragent/turn-stale"]
    # tag 仍在 —— dry_run 没动手
    assert "xragent/turn-stale" in sg.list_snapshots()


def test_cleanup_old_snapshots_disabled_when_max_age_zero(repo_root):
    """max_age_days <= 0 表示禁用清理：直接返回 []，不动任何 tag。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-ancient", "ancient", now - 365 * 86400)

    for v in (0, -1, -30):
        assert sg.cleanup_old_snapshots(max_age_days=v) == []
        assert sg.cleanup_old_snapshots(max_age_days=v, dry_run=True) == []
        assert "xragent/turn-ancient" in sg.list_snapshots()


def test_cleanup_old_snapshots_empty_when_nothing_old(repo_root):
    """所有 tag 都在保留期内 → 返回 []，且原列表不动。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-a", "a", now - 5 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-b", "b", now - 10 * 86400)

    before = sg.list_snapshots()
    removed = sg.cleanup_old_snapshots(max_age_days=30)
    assert removed == []
    assert sg.list_snapshots() == before


def test_cleanup_old_snapshots_default_uses_settings(repo_root):
    """不传 max_age_days 时走 settings.snapshot_retention_days（默认 30）。"""
    from xragent.config import settings as settings_mod

    settings_mod.get_settings().snapshot_retention_days = 30

    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-15d", "15 days", now - 15 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-45d", "45 days", now - 45 * 86400)

    removed = sg.cleanup_old_snapshots()  # 不传 → 默认 30
    assert "xragent/turn-45d" in removed
    assert "xragent/turn-15d" not in removed


def test_cleanup_old_snapshots_not_a_repo_is_noop(repo_root):
    """非 git 仓库时静默返回 []，不抛 —— watchdog/cron 调用不应炸流程。

    用 repo_root fixture 起一个仓库，删掉 .git 后再调 cleanup，验证
    is_repo() 失败路径走通、且不抛异常。
    """
    shutil.rmtree(repo_root / ".git")
    sg = SideGit()
    assert sg.is_repo() is False
    assert sg.cleanup_old_snapshots(max_age_days=30) == []
    assert sg.cleanup_old_snapshots(max_age_days=30, dry_run=True) == []


def test_cleanup_old_snapshots_ignores_non_xragent_tags(repo_root):
    """非 ``xragent/turn-*`` 前缀的 tag 不应被误删。

    用户手工打的 ``v0.1`` / ``baseline`` 等里程碑 tag 必须保留——cleanup
    只动 ``xragent/turn-*`` 自动前缀。这是 watch-through 边角契约：refspec
    ``refs/tags/xragent/turn-*`` 自然只匹配自动前缀,但仍需白盒锁行为。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    old_ts = now - 60 * 86400  # 全部都在 30 天阈值外
    _make_annotated_tag(str(repo_root), "v0.1", "user milestone", old_ts)
    _make_annotated_tag(str(repo_root), "baseline", "user tag", old_ts)
    _make_annotated_tag(str(repo_root), "xragent/turn-stale", "auto", old_ts)

    removed = sg.cleanup_old_snapshots(max_age_days=30)
    # 只删自动前缀的快照
    assert removed == ["xragent/turn-stale"]

    # user 手工 tag 仍在（直接 git tag -l 验证,不只信 list_snapshots）
    all_tags = subprocess.run(
        ["git", "tag", "-l"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "v0.1" in all_tags
    assert "baseline" in all_tags
    assert "xragent/turn-stale" not in all_tags