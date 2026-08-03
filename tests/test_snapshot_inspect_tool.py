"""``git_tools.snapshot_inspect`` 工具包装层契约（v0.5.6）。

底层 :mod:`xragent.snapshot.inspect` 的三件套（``SnapshotMeta.to_dict``
/ ``list_snapshots_with_meta`` / ``count_over_age`` /
``format_snapshot_table``）的完整契约已在 ``tests/test_snapshot_inspect.py``
锁住。本文件只覆盖 *工具包装层* 的 LLM 契约：

  * ``format="table"`` (默认) → 返回 ``ok / count / format / table`` 四键
  * ``format="dict"`` → 返回 ``ok / count / format / snapshots`` 四键
  * ``max_age_days`` 不传 → 不出现 ``count_over_age`` 键
  * ``max_age_days`` 传了 → 出现 ``count_over_age`` 整数
  * ``format`` 取非法值 → ``ok=False, msg=<诊断>``（不抛）
  * 非 git 仓库 → 静默 ``count=0``，不抛（继承 inspect 的非 git 静默语义）
  * 工具返回值 *严格* 是 ``dict`` (LLM 解析契约)
  * ``format`` 字段必须透传输入
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from xragent.snapshot.side_git import SideGit
from xragent.tools import git_tools


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_annotated_tag(repo: Path, tag: str, message: str, unix_ts: int) -> None:
    """把 annotated tag 的 creatordate 倒拨到 unix_ts。

    与 ``tests/test_git_tools.py`` / ``tests/test_sidegit_cleanup.py`` 里的
    helper 同款：用 ``GIT_COMMITTER_DATE`` / ``GIT_AUTHOR_DATE`` 倒拨时间,
    无需 monkeypatch 真实时钟。
    """
    import os
    import time as _time

    env = os.environ.copy()
    iso = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime(unix_ts))
    env["GIT_COMMITTER_DATE"] = iso
    env["GIT_AUTHOR_DATE"] = iso
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", message],
        cwd=str(repo),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# format=table (默认)
# ---------------------------------------------------------------------------


def test_snapshot_inspect_empty_repo_returns_table_with_zero_count(repo_root: Path):
    """conftest 初始化时仓库没有任何 xragent/turn-* tag → table="# 0 snapshots"。

    这是 *最常见的 HITL 场景*：Agent 上线第一天，仓库还是空的。
    """
    r = git_tools.snapshot_inspect()
    assert isinstance(r, dict)
    assert r["ok"] is True
    assert r["count"] == 0
    assert r["format"] == "table"
    # 严格只含 4 个键 (无 max_age_days → 不含 count_over_age)
    assert set(r.keys()) == {"ok", "count", "format", "table"}
    assert "# 0 snapshots" in r["table"]
    assert r["table"].endswith("\n")


def test_snapshot_inspect_table_format_lists_real_tags_newest_first(repo_root: Path):
    """format=table 拉真实 tag → 按 creatordate 倒序出现在 table 字符串里。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    old_ts = now - 60 * 86400
    mid_ts = now - 30 * 86400
    new_ts = now - 5 * 86400
    _make_annotated_tag(repo_root, "xragent/turn-v056-old", "old", old_ts)
    _make_annotated_tag(repo_root, "xragent/turn-v056-mid", "mid", mid_ts)
    _make_annotated_tag(repo_root, "xragent/turn-v056-new", "new", new_ts)

    r = git_tools.snapshot_inspect()
    assert r["ok"] is True
    assert r["count"] == 3
    assert r["format"] == "table"
    assert set(r.keys()) == {"ok", "count", "format", "table"}

    lines = r["table"].splitlines()
    # 第一行是 "# 3 snapshots"
    assert lines[0] == "# 3 snapshots"
    # 倒序: new → mid → old
    new_idx = next(i for i, ln in enumerate(lines) if "xragent/turn-v056-new" in ln)
    mid_idx = next(i for i, ln in enumerate(lines) if "xragent/turn-v056-mid" in ln)
    old_idx = next(i for i, ln in enumerate(lines) if "xragent/turn-v056-old" in ln)
    assert new_idx < mid_idx < old_idx, (
        f"未按倒序排列: new={new_idx}, mid={mid_idx}, old={old_idx}"
    )


# ---------------------------------------------------------------------------
# format=dict
# ---------------------------------------------------------------------------


def test_snapshot_inspect_dict_format_returns_six_field_snapshots(repo_root: Path):
    """format=dict → snapshots 是 list[dict]，每个 dict 含 6 字段（与 to_dict 对齐）。

    这是 LLM 二次推理（"挑 age > 30 的有哪些"）的入口 — 必须结构化。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(repo_root, "xragent/turn-v056-dict", "d", now - 7 * 86400)

    r = git_tools.snapshot_inspect(format="dict")
    assert r["ok"] is True
    assert r["count"] == 1
    assert r["format"] == "dict"
    # 严格只含 4 个键
    assert set(r.keys()) == {"ok", "count", "format", "snapshots"}

    snaps = r["snapshots"]
    assert isinstance(snaps, list)
    assert len(snaps) == 1
    s = snaps[0]
    assert set(s.keys()) == {
        "name", "ts", "iso_year", "iso_week", "age_in_days", "creatordate_iso",
    }
    assert s["name"] == "xragent/turn-v056-dict"
    assert isinstance(s["ts"], int)
    assert isinstance(s["iso_year"], int)
    assert isinstance(s["iso_week"], int)
    assert isinstance(s["age_in_days"], (int, float))
    assert isinstance(s["creatordate_iso"], str)
    assert s["creatordate_iso"].endswith("Z")


# ---------------------------------------------------------------------------
# max_age_days 联动
# ---------------------------------------------------------------------------


def test_snapshot_inspect_without_max_age_days_omits_count_over_age(repo_root: Path):
    """不传 max_age_days → 结果里 *没有* count_over_age 字段。

    LLM 契约的"最小键集"原则：不传就不出，避免 LLM 误读 stale 0。
    """
    r = git_tools.snapshot_inspect()
    assert "count_over_age" not in r


def test_snapshot_inspect_with_max_age_days_adds_count_over_age(repo_root: Path):
    """传 max_age_days → 结果里加 count_over_age 整数（与 cleanup 同语义）。

    配合 :func:`snapshot_cleanup` 用的"先 inspect 看会清几个，再决定清不清"
    工作流。
    """
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    # 50 天前 + 10 天前 → 默认 30 天阈值下, 50 天前会超期, 10 天前不会
    _make_annotated_tag(repo_root, "xragent/turn-v056-old50", "old50", now - 50 * 86400)
    _make_annotated_tag(repo_root, "xragent/turn-v056-young10", "y10", now - 10 * 86400)

    r = git_tools.snapshot_inspect(max_age_days=30)
    assert r["ok"] is True
    assert r["count"] == 2  # 总数仍是 2
    # 严格只含 5 个键 (count_over_age 出现)
    assert set(r.keys()) == {"ok", "count", "format", "table", "count_over_age"}
    assert r["count_over_age"] == 1  # 只有 50 天前那个超期


def test_snapshot_inspect_count_over_age_zero_when_nothing_old(repo_root: Path):
    """全年轻 tag → count_over_age=0（语义对齐 cleanup 的"删 0 个"预览）。"""
    sg = SideGit()
    sg.ensure_repo()

    now = int(time.time())
    _make_annotated_tag(repo_root, "xragent/turn-v056-fresh", "f", now - 86400)

    r = git_tools.snapshot_inspect(max_age_days=30)
    assert r["count"] == 1
    assert r["count_over_age"] == 0


# ---------------------------------------------------------------------------
# 非法参数兜底
# ---------------------------------------------------------------------------


def test_snapshot_inspect_invalid_format_returns_ok_false(repo_root: Path):
    """format 传非 ('table'|'dict') → ``ok=False, msg=<诊断>``，不抛。

    锁定：实现走 ``_fail(...)`` 路径（与 snapshot_cleanup 异常路径一致），
    而不是抛 ``ValueError`` —— LLM 看到 exception envelope 会困惑。
    """
    r = git_tools.snapshot_inspect(format="json")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "msg" in r
    assert "format" in r["msg"]
    assert "json" in r["msg"]  # 透传错误值便于诊断
    # 严格只含 2 个键 (ok + msg)，没有别的
    assert set(r.keys()) == {"ok", "msg"}


# ---------------------------------------------------------------------------
# LLM 契约 / 烟雾
# ---------------------------------------------------------------------------


def test_snapshot_inspect_returns_dict_in_all_paths(repo_root: Path):
    """无论 ok 还是非 ok, 返回值必须严格是 ``dict`` —— LLM JSON 解析契约。

    抽 3 个分支各跑一遍（empty / with-tag / 非法 format）确保类型一致。
    """
    assert isinstance(git_tools.snapshot_inspect(), dict)
    assert isinstance(git_tools.snapshot_inspect(format="dict"), dict)
    assert isinstance(git_tools.snapshot_inspect(format="invalid"), dict)


def test_snapshot_inspect_format_field_always_passes_through(repo_root: Path):
    """``format`` 字段必须 *透传* 输入（便于 LLM 区分"我刚请求的是哪种"）。

    即使是 ``ok=False`` 分支, format 字段也应在 (此处非法值会被映射到
    ok=False, 故不在本测试范围) — 但 *合法* 取值 table / dict 必须 1:1 透传。
    """
    assert git_tools.snapshot_inspect()["format"] == "table"
    assert git_tools.snapshot_inspect(format="table")["format"] == "table"
    assert git_tools.snapshot_inspect(format="dict")["format"] == "dict"
