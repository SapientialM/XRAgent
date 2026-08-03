"""``snapshot.inspect`` 的只读查询契约 —— 给父母 / HITL 看 snapshot 用。

覆盖:
  * :class:`SnapshotMeta.to_dict` 字段完整 + 类型正确
  * :func:`list_snapshots_with_meta` 倒序 (最新在前) + 非 git 仓库静默 ``[]``
  * :func:`count_over_age` cutoff 严格小于语义 (与 ``age_cleanup`` 对齐)
  * :func:`format_snapshot_table` 对齐列 + 空列表 ``# 0 snapshots`` 行

不重复 ``tests/test_age_cleanup.py`` 里已有的"删"路径契约;本文件只
锁定 *新增的* 只读 inspect 路径。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from xragent.snapshot import inspect as insp


class _FakeSideGit:
    """``SideGit`` 接口最小 fake —— 只 mock ``is_repo()`` + ``_run()``。

    复用 ``xragent.snapshot._tag_index.list_xragent_turn_tags`` 走
    ``is_repo`` / ``_run``,所以 fake 只暴露这两个方法。
    """

    def __init__(self, rows: list[tuple[int, str]] | None = None, *, is_repo: bool = True) -> None:
        self._is_repo = is_repo
        # rows: [(ts, name)] —— 会被格式化成 for-each-ref 行
        self._rows = rows or []

    def is_repo(self) -> bool:
        return self._is_repo

    def _run(self, *args: Any, **kwargs: Any) -> str:
        # 只支持 ``for-each-ref ...`` 调用: 把 rows 拼成 ``name\\tts`` 行
        if args and args[0] == "for-each-ref":
            return "\n".join(f"{name}\t{ts}" for ts, name in self._rows)
        raise RuntimeError(f"unexpected _run args: {args}")


def _meta(name: str, ts: int, now: float) -> insp.SnapshotMeta:
    """helper: 单点造 SnapshotMeta (不走 list 入口,便于测单字段)。"""
    return insp._build_meta(ts, name, now)


# ---------------------------------------------------------------------------
# SnapshotMeta + to_dict
# ---------------------------------------------------------------------------


def test_meta_to_dict_has_six_fields():
    """``to_dict`` 必须返回 6 字段且类型正确 (HTTP / 日志序列化依赖)。"""
    m = _meta("xragent/turn-x", 1_700_000_000, now=1_700_000_000 + 3 * 86400)
    d = m.to_dict()
    assert set(d.keys()) == {
        "name", "ts", "iso_year", "iso_week", "age_in_days", "creatordate_iso"
    }
    assert isinstance(d["ts"], int)
    assert isinstance(d["iso_year"], int)
    assert isinstance(d["iso_week"], int)
    assert isinstance(d["age_in_days"], float)
    assert isinstance(d["creatordate_iso"], str)
    assert d["name"] == "xragent/turn-x"


def test_meta_age_is_now_minus_ts_over_86400():
    """``age_in_days`` 必须严格按 (now - ts) / 86400 计算 (浮点)。"""
    now = 1_700_000_000.0
    m = _meta("xragent/turn-x", ts=now - 5 * 86400, now=now)
    assert m.age_in_days == 5.0


def test_meta_iso_week_handles_cross_year():
    """跨年 ISO 周 (1 月初几天属上一 ISO 年) 必须正确归位。

    2026-01-01 是周四 → ISO 周 = 2026-W01。
    2025-12-31 是周三 → ISO 周 = 2025-W53 (用 2025 年的 ISO 周,不是 2026-W01)。
    """
    ts_2026_01_01 = int(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    ts_2025_12_31 = int(dt.datetime(2025, 12, 31, tzinfo=dt.timezone.utc).timestamp())
    m_jan = _meta("xragent/turn-jan1", ts=ts_2026_01_01, now=ts_2026_01_01 + 1)
    m_dec = _meta("xragent/turn-dec31", ts=ts_2025_12_31, now=ts_2025_12_31 + 1)
    assert (m_jan.iso_year, m_jan.iso_week) == (2026, 1)
    assert (m_dec.iso_year, m_dec.iso_week) == (2025, 53)


def test_meta_creatordate_iso_is_utc_z_suffix():
    """``creatordate_iso`` 必须 UTC ISO 8601 + ``Z`` 后缀 (便于跨时区阅读)。"""
    ts = int(dt.datetime(2026, 8, 2, 10, 30, 0, tzinfo=dt.timezone.utc).timestamp())
    m = _meta("xragent/turn-x", ts=ts, now=ts + 1)
    assert m.creatordate_iso == "2026-08-02T10:30:00Z"


# ---------------------------------------------------------------------------
# list_snapshots_with_meta
# ---------------------------------------------------------------------------


def test_list_returns_empty_when_not_a_repo():
    """非 git 仓库 → 静默 ``[]``,不抛 (与 ``list_xragent_turn_tags`` 对齐)。"""
    fake = _FakeSideGit(is_repo=False)
    assert insp.list_snapshots_with_meta(fake, now=1_700_000_000.0) == []


def test_list_returns_empty_when_no_tags():
    """git 仓库但无 ``xragent/turn-*`` tag → ``[]`` (走 ``_run`` 抛 RuntimeError 静默吞)。"""
    fake = _FakeSideGit(rows=[])  # 空 → for-each-ref exit 1, list_xragent_turn_tags 静默吞
    assert insp.list_snapshots_with_meta(fake, now=1_700_000_000.0) == []


def test_list_returns_metas_newest_first():
    """snapshot tag 必须 *倒序* 输出 (最新在前) —— 给人看的列表顺序。"""
    rows = [
        (1_700_000_000, "xragent/turn-old"),
        (1_710_000_000, "xragent/turn-mid"),
        (1_720_000_000, "xragent/turn-new"),
    ]
    fake = _FakeSideGit(rows=rows)
    out = insp.list_snapshots_with_meta(fake, now=1_720_000_000.0 + 100)
    assert [m.name for m in out] == [
        "xragent/turn-new", "xragent/turn-mid", "xragent/turn-old",
    ]


def test_list_injects_now_for_deterministic_age():
    """``now`` 注入必须被尊重 —— 单测里固定 ``now``,不依赖 ``time.time()``。"""
    rows = [(1_700_000_000, "xragent/turn-x")]
    fake = _FakeSideGit(rows=rows)
    fixed_now = 1_700_000_000.0 + 7 * 86400
    metas = insp.list_snapshots_with_meta(fake, now=fixed_now)
    assert len(metas) == 1
    assert metas[0].age_in_days == 7.0


# ---------------------------------------------------------------------------
# count_over_age
# ---------------------------------------------------------------------------


def test_count_over_age_strict_lt_cutoff():
    """cutoff 严格小于 (与 ``age_cleanup.cleanup_old_snapshots_by_age`` 对齐)。

    30 天前的 tag 在 max_age_days=30 时 *会* 被算超期;
    恰好整 30 天 (边界) *不* 算超期 —— ``ts < cutoff`` 语义。
    """
    now = 1_720_000_000.0
    rows = [
        (int(now) - 31 * 86400, "xragent/turn-31d"),   # 超期
        (int(now) - 30 * 86400, "xragent/turn-30d"),   # 边界: 不超期
        (int(now) - 29 * 86400, "xragent/turn-29d"),   # 不超期
        (int(now) - 60 * 86400, "xragent/turn-60d"),   # 超期
    ]
    fake = _FakeSideGit(rows=rows)
    assert insp.count_over_age(fake, max_age_days=30, now=now) == 2


def test_count_over_age_no_repo_returns_zero():
    """非 git 仓库 → ``0`` (不抛)。"""
    fake = _FakeSideGit(is_repo=False)
    assert insp.count_over_age(fake, max_age_days=30, now=1_720_000_000.0) == 0


def test_count_over_age_zero_threshold_counts_everything():
    """``max_age_days=0`` → cutoff == now, 所有 ``ts < now`` 都算超期。

    注意: 这与 ``age_cleanup.cleanup_old_snapshots_by_age`` 在 ``<= 0`` 时
    *禁用* 的语义不同 —— ``count_over_age`` 是镜像计数,不动写路径,
    单独把 ``<= 0`` 当作 "全部超期" 处理 (便于 HITL 显示 "如果不设
    阈值,有多少?" 这种 *假设性* 问题)。
    """
    now = 1_720_000_000.0
    rows = [
        (int(now) - 86400, "xragent/turn-1d"),
        (int(now) - 60 * 86400, "xragent/turn-60d"),
    ]
    fake = _FakeSideGit(rows=rows)
    assert insp.count_over_age(fake, max_age_days=0, now=now) == 2


# ---------------------------------------------------------------------------
# format_snapshot_table
# ---------------------------------------------------------------------------


def test_format_empty_list():
    """空列表 → 单独一行 ``# 0 snapshots\\n``, 无表格头 (避免噪声)。"""
    assert insp.format_snapshot_table([]) == "# 0 snapshots\n"


def test_format_columns_are_aligned():
    """表格列必须对齐: AGE 右对齐, ISO/CREATED/NAME 左对齐, NAME 不截断。"""
    metas = [
        insp._build_meta(
            ts=1_720_000_000, name="xragent/turn-new", now=1_720_000_000.0 + 2 * 86400,
        ),
        insp._build_meta(
            ts=1_700_000_000, name="xragent/turn-old", now=1_720_000_000.0 + 60 * 86400,
        ),
    ]
    out = insp.format_snapshot_table(metas).splitlines()
    assert out[0] == "# 2 snapshots"
    # 表头
    assert out[1].startswith("  AGE")  # 5 字符右对齐 → AGE 前面 2 个空 (5-3) + 'AGE'
    assert "ISO" in out[1]
    assert "CREATED" in out[1]
    assert "NAME" in out[1]
    # 数据行: 必须含 tag 名 (NAME 列不截断)
    assert "xragent/turn-new" in out[2]
    assert "xragent/turn-old" in out[3]


def test_format_ends_with_newline():
    """末尾必须保留 ``\\n`` (便于 ``print`` / 写文件不污染下一行)。"""
    metas = [insp._build_meta(ts=1_700_000_000, name="x", now=1_700_000_000.0 + 86400)]
    assert insp.format_snapshot_table(metas).endswith("\n")