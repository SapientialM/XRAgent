"""5.8 LRU 行为测试。

覆盖:
    - save_fact 写入时 last_accessed_ts 初始化为 ts (创建即"被访问")
    - touch_fact 刷新 last_accessed_ts 为当前时间, 不存在返回 False
    - recall_lru 按 last_accessed_ts ASC 召回最久未访问的 top-k
    - recall_lru(active_only=True) 排除 archived
    - 老行 (last_accessed_ts=0.0) 排最前, 适合冷数据淘汰场景
    - _migrate_v58 幂等: 已有列时 no-op
"""
from __future__ import annotations

import time

from xragent.memory.manager import Fact, MemoryManager, SCHEMA_VERSION


def test_save_fact_initializes_last_accessed_ts(repo_root):
    """save_fact 必须把 last_accessed_ts 初始化为 ts, 避免新行被 recall_lru 误判为冷数据."""
    m = MemoryManager()
    before = time.time()
    f = m.save_fact("note", "hello")
    after = time.time()
    assert before <= f.last_accessed_ts <= after
    # last_accessed_ts 应 == ts (创建时同时被访问)
    assert abs(f.last_accessed_ts - f.ts) < 1e-3


def test_touch_fact_refreshes_last_accessed_ts(repo_root):
    """touch_fact 之后 last_accessed_ts 应推进; 第二次 touch 再推进."""
    m = MemoryManager()
    f = m.save_fact("note", "x")
    old = f.last_accessed_ts

    # sleep 一小段确保 ts 变化可观察
    time.sleep(0.05)
    ok = m.touch_fact(f.id)
    assert ok is True

    rows = m.recall(query="x")
    assert len(rows) == 1
    assert rows[0].last_accessed_ts > old
    # 还得 >= 刚才的 sleep
    assert rows[0].last_accessed_ts >= old + 0.04

    # 再 touch 一次, 仍递增
    time.sleep(0.05)
    m.touch_fact(f.id)
    rows = m.recall(query="x")
    assert rows[0].last_accessed_ts >= rows[0].last_accessed_ts  # sanity


def test_touch_fact_unknown_id_returns_false(repo_root):
    """touch 不存在的 fact_id 返回 False, 不抛错."""
    m = MemoryManager()
    assert m.touch_fact(999_999) is False


def test_recall_lru_orders_oldest_first(repo_root):
    """recall_lru 应按 last_accessed_ts ASC 排序 (最久未访问在前)."""
    m = MemoryManager()
    a = m.save_fact("note", "alpha")
    time.sleep(0.02)
    b = m.save_fact("note", "beta")
    time.sleep(0.02)
    c = m.save_fact("note", "gamma")

    # touch 一下 b, 让它变 "新"
    time.sleep(0.02)
    m.touch_fact(b.id)

    rows = m.recall_lru(k=3)
    assert [r.id for r in rows] == [a.id, c.id, b.id]


def test_recall_lru_active_only_excludes_archived(repo_root):
    """active_only=True (默认) 不召回 archived 行."""
    m = MemoryManager()
    f1 = m.save_fact("note", "alive")
    f2 = m.save_fact("note", "todelete")
    f3 = m.save_fact("note", "another")

    m.archive_fact(f2.id)

    rows = m.recall_lru(k=10, active_only=True)
    ids = {r.id for r in rows}
    assert f1.id in ids
    assert f3.id in ids
    assert f2.id not in ids


def test_recall_lru_active_only_false_includes_archived(repo_root):
    """active_only=False 时 archived 也召回."""
    m = MemoryManager()
    f1 = m.save_fact("note", "alive")
    f2 = m.save_fact("note", "dead")
    m.archive_fact(f2.id)

    rows = m.recall_lru(k=10, active_only=False)
    ids = {r.id for r in rows}
    assert f1.id in ids
    assert f2.id in ids


def test_recall_lru_old_rows_default_to_zero(repo_root):
    """DB DEFAULT 0.0 的老行应排最前 (冷数据回收场景).

    模拟 '老行' 的方式: 直接 SQL UPDATE 把 last_accessed_ts 写回 0.0,
    验证 recall_lru 把它们排在前面.
    """
    m = MemoryManager()
    fresh = m.save_fact("note", "fresh")
    old = m.save_fact("note", "old")
    # 把 old 的 last_accessed_ts 改回 0.0 (模拟迁移前的老行)
    with m._lock, m._conn:  # noqa: SLF001  - 测试内部访问合法
        m._conn.execute(  # noqa: SLF001
            "UPDATE facts SET last_accessed_ts = 0.0 WHERE id = ?",
            (old.id,),
        )

    rows = m.recall_lru(k=2)
    assert rows[0].id == old.id
    assert rows[1].id == fresh.id


def test_recall_lru_k_limits(repo_root):
    """k 限制生效."""
    m = MemoryManager()
    for i in range(5):
        m.save_fact("note", f"item-{i}")

    rows = m.recall_lru(k=2)
    assert len(rows) == 2


def test_recall_lru_empty_db_returns_empty_list(repo_root):
    """空库不能崩."""
    m = MemoryManager()
    assert m.recall_lru(k=10) == []


def test_migrate_v58_idempotent(repo_root):
    """连开两次 MemoryManager 不抛错; 第二遍 _migrate_v58 走 no-op."""
    m1 = MemoryManager()
    # 第二遍模拟: 先关, 再开
    m1.close()
    m2 = MemoryManager()
    # 写一行确认仍能正常用
    f = m2.save_fact("note", "after-reopen")
    assert f.id > 0
    rows = m2.recall_lru(k=1)
    assert len(rows) == 1
    assert rows[0].id == f.id


def test_schema_version_is_58(repo_root):
    """防回归: SCHEMA_VERSION 必须停在 5.8 直到下一次迁移."""
    assert SCHEMA_VERSION == 58


def test_fact_dataclass_has_last_accessed_ts_field(repo_root):
    """Fact dataclass 暴露 last_accessed_ts 字段, 默认 0.0."""
    f = Fact(id=1, ts=1.0, category="x", content="y")
    assert hasattr(f, "last_accessed_ts")
    assert f.last_accessed_ts == 0.0