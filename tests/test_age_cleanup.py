"""``snapshot.age_cleanup.cleanup_old_snapshots_by_age`` 行为契约。

与 ``test_count_cleanup.py`` 同源风格：``repo_root`` fixture 起真 git
repo，``_make_annotated_tag`` 用 ``GIT_COMMITTER_DATE`` 倒拨 creatordate
来控制"新旧"——无需 monkeypatch 真实时钟。``count_cleanup.py`` 的镜像
测试，无需再覆盖 ``SideGit.cleanup_old_snapshots``（那条路径由
``test_sidegit_cleanup.py`` 覆盖）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from xragent.snapshot.age_cleanup import cleanup_old_snapshots_by_age
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


def test_age_cleanup_disabled_when_max_age_zero(repo_root):
    """``max_age_days <= 0`` → 禁用清理：直接返回 ``[]``，不动任何 tag。

    None 路径走 settings.snapshot_retention_days 默认 30 —— 这里不展开测
    （settings 单测在 settings 模块），只锁 ``<= 0`` 禁用语义。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-a", "a", now - 100 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-b", "b", now - 365 * 86400)

    for v in (0, -1, -30):
        assert cleanup_old_snapshots_by_age(sg, max_age_days=v) == []
        assert cleanup_old_snapshots_by_age(sg, max_age_days=v, dry_run=True) == []
        # tag 仍在
        assert "xragent/turn-a" in sg.list_snapshots()
        assert "xragent/turn-b" in sg.list_snapshots()


def test_age_cleanup_removes_only_old_tags(repo_root):
    """31 天前的 tag 应被删；7 天前的应保留。

    cutoff = now - 30*86400 → ``ts < cutoff`` 严格小于，所以 31 天前
    (now - 31*86400) 在 cutoff 之前 → 删；7 天前 (now - 7*86400) 在
    cutoff 之后 → 保留。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-old", "old snap", now - 31 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-fresh", "fresh snap", now - 7 * 86400)

    removed = cleanup_old_snapshots_by_age(sg, max_age_days=30)
    assert "xragent/turn-old" in removed
    assert "xragent/turn-fresh" not in removed
    # 实际 tag 列表也应只剩 fresh
    assert sg.list_snapshots() == ["xragent/turn-fresh"]


def test_age_cleanup_dry_run_lists_but_does_not_delete(repo_root):
    """``dry_run=True`` 只列候选，不执行 ``git tag -d``。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-stale", "stale", now - 40 * 86400)

    listed = cleanup_old_snapshots_by_age(sg, max_age_days=30, dry_run=True)
    assert listed == ["xragent/turn-stale"]
    # tag 仍在 —— dry_run 没动手
    assert "xragent/turn-stale" in sg.list_snapshots()


def test_age_cleanup_empty_when_nothing_old(repo_root):
    """所有 tag 都在保留期内 → 返回 ``[]``，且原列表不动。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(str(repo_root), "xragent/turn-a", "a", now - 5 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-b", "b", now - 10 * 86400)

    before = sg.list_snapshots()
    removed = cleanup_old_snapshots_by_age(sg, max_age_days=30)
    assert removed == []
    assert sg.list_snapshots() == before


def test_age_cleanup_results_sorted_oldest_first(repo_root):
    """返回列表按 creatordate 旧→新排序 —— 与 :meth:`SideGit.cleanup_old_snapshots` 对齐。

    3 个超期 tag 间隔 1 天，确认排序方向而非巧合顺序。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    # 同名不同间隔避免冲突；最新→最旧依次打
    _make_annotated_tag(str(repo_root), "xragent/turn-45d", "45 days", now - 45 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-60d", "60 days", now - 60 * 86400)
    _make_annotated_tag(str(repo_root), "xragent/turn-90d", "90 days", now - 90 * 86400)

    removed = cleanup_old_snapshots_by_age(sg, max_age_days=30)
    # 旧→新：90d, 60d, 45d
    assert removed == ["xragent/turn-90d", "xragent/turn-60d", "xragent/turn-45d"]
    assert sg.list_snapshots() == []


def test_age_cleanup_ignores_non_xragent_tags(repo_root):
    """非 ``xragent/turn-*`` 前缀的 tag 不应被误删。

    用户手工打的 ``v0.1`` / ``baseline`` 等里程碑 tag 必须保留——本模块
    只动 ``xragent/turn-*`` 自动前缀。这是 watch-through 边角契约。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    old_ts = now - 60 * 86400  # 全部都在 30 天阈值外
    _make_annotated_tag(str(repo_root), "v0.1", "user milestone", old_ts)
    _make_annotated_tag(str(repo_root), "baseline", "user tag", old_ts)
    _make_annotated_tag(str(repo_root), "xragent/turn-stale", "auto", old_ts)

    removed = cleanup_old_snapshots_by_age(sg, max_age_days=30)
    # 只删自动前缀的快照
    assert removed == ["xragent/turn-stale"]

    # user 手工 tag 仍在（直接 git tag -l 验证，不只信 list_snapshots）
    all_tags = subprocess.run(
        ["git", "tag", "-l"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "v0.1" in all_tags
    assert "baseline" in all_tags
    assert "xragent/turn-stale" not in all_tags


def test_age_cleanup_not_a_repo_is_noop(repo_root):
    """非 git 仓库时静默返回 ``[]``，不抛 —— watchdog/cron 调用不应炸流程。

    用 ``repo_root`` fixture 起一个仓库，删掉 ``.git`` 后再调 cleanup，
    验证 ``is_repo()`` 失败路径走通、且不抛异常。
    """
    shutil.rmtree(repo_root / ".git")
    sg = SideGit()
    assert sg.is_repo() is False
    assert cleanup_old_snapshots_by_age(sg, max_age_days=30) == []
    assert cleanup_old_snapshots_by_age(sg, max_age_days=30, dry_run=True) == []


def test_age_cleanup_empty_repo_is_noop(repo_root):
    """合法 git 仓库但没有任何 ``xragent/turn-*`` tag → 返回 ``[]``。

    ``git for-each-ref refs/tags/xragent/turn-*`` 在无匹配时 exit 1，本模块
    必须静默吞下并返回空列表，而不是让调用方炸 RuntimeError。
    """
    sg = SideGit()
    sg.ensure_repo()
    # 仓库里没有任何 xragent/turn-* tag —— 验证 for-each-ref exit 1 路径走通
    assert sg.list_snapshots() == []
    assert cleanup_old_snapshots_by_age(sg, max_age_days=5) == []
    assert cleanup_old_snapshots_by_age(sg, max_age_days=5, dry_run=True) == []


def test_age_cleanup_mixed_old_and_fresh_keeps_fresh(repo_root):
    """混合新旧 tag：只删超期的，新鲜的留下。

    比 ``test_age_cleanup_removes_only_old_tags`` 多一个 tag，确认中间
    区间（15 天）的 tag 不被误删、且 60 天前被正确清理。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    for name, days_ago in [
        ("xragent/turn-3d", 3),
        ("xragent/turn-15d", 15),
        ("xragent/turn-29d", 29),  # 边界内（cutoff=now-30d → ts < cutoff 即删；29d > cutoff → 保留）
        ("xragent/turn-60d", 60),
    ]:
        _make_annotated_tag(
            str(repo_root), name, name, now - days_ago * 86400,
        )

    removed = cleanup_old_snapshots_by_age(sg, max_age_days=30)
    # 只删 60d 那一个
    assert removed == ["xragent/turn-60d"]
    # 剩余按 creatordate 倒序（新→旧）: 3d, 15d, 29d
    assert sg.list_snapshots() == [
        "xragent/turn-3d",
        "xragent/turn-15d",
        "xragent/turn-29d",
    ]