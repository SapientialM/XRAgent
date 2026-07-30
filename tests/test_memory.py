"""MemoryManager：SQLite 事实存取。"""
from __future__ import annotations

import time

from xragent.memory.manager import Fact, MemoryManager


def test_save_and_recall(repo_root):
    """5.1: save_fact 现在返回 Fact 而非 int, 验证字段全部填充。"""
    m = MemoryManager()
    f = m.save_fact("preference", "user 喜欢 Python", source_turn="t1")
    assert isinstance(f, Fact)
    assert f.id > 0
    assert f.category == "preference"
    assert f.content == "user 喜欢 Python"
    assert f.source_turn == "t1"
    # 没传 source_turn_idx 时为 None (向后兼容老调用)
    assert f.source_turn_idx is None
    results = m.recall("Python")
    assert any(x.id == f.id for x in results)
    assert any(x.content == "user 喜欢 Python" for x in results)


def test_save_fact_preserves_source_turn_idx(repo_root):
    """5.1: 新字段 source_turn_idx 持久化 + recall 出来能读到。"""
    m = MemoryManager()
    f = m.save_fact("note", "round 7 笔记", source_turn="t7", source_turn_idx=7)
    assert f.source_turn_idx == 7
    # 落库后再 recall, 新字段也应在
    hits = m.recall("round 7")
    assert hits and hits[0].source_turn_idx == 7


def test_recall_with_category_filter(repo_root):
    m = MemoryManager()
    m.save_fact("preference", "user 喜欢 Rust")
    m.save_fact("history", "user 写过 C++")
    pref = m.recall("user", k=10, category="preference")
    assert all(f.category == "preference" for f in pref)
    assert any("Rust" in f.content for f in pref)
    hist = m.recall("user", k=10, category="history")
    assert all(f.category == "history" for f in hist)


def test_recall_range_by_timestamp(repo_root):
    """recall_range 按时间窗口召回。新方法覆盖"什么时候说的"路径。"""
    m = MemoryManager()
    t0 = time.time()
    m.save_fact("note", "earlier fact")
    time.sleep(0.05)
    t_mid = time.time()
    time.sleep(0.05)
    m.save_fact("note", "later fact")
    later_ts = time.time()

    earlier = m.recall_range(start_ts=t0, end_ts=t_mid)
    later = m.recall_range(start_ts=t_mid, end_ts=later_ts + 1)
    assert len(earlier) == 1 and "earlier" in earlier[0].content
    assert len(later) == 1 and "later" in later[0].content


def test_recall_range_open_bounds(repo_root):
    """start_ts/end_ts 为 None 时表示开放端。"""
    m = MemoryManager()
    m.save_fact("note", "open bound fact")
    facts = m.recall_range()
    assert len(facts) >= 1
    facts = m.recall_range(start_ts=0.0)
    assert any(f.content == "open bound fact" for f in facts)
    facts = m.recall_range(end_ts=time.time() + 1000)
    assert any(f.content == "open bound fact" for f in facts)


def test_top_frequent_basic(repo_root):
    """同 content 出现多次应排到 top。"""
    m = MemoryManager()
    for _ in range(3):
        m.save_fact("preference", "user 喜欢简洁")
    for _ in range(2):
        m.save_fact("preference", "user 喜欢 Rust")
    m.save_fact("preference", "noise one-off")

    top = m.top_frequent(n=5, category="preference", min_count=2)
    contents = [c for c, _ in top]
    assert "user 喜欢简洁" in contents
    assert "noise one-off" not in contents
    # 出现 3 次的应排在 2 次之前
    rank = {c: i for i, (c, _) in enumerate(top)}
    assert rank["user 喜欢简洁"] < rank["user 喜欢 Rust"]


def test_top_frequent_category_isolation(repo_root):
    """同 content 在不同 category 下应分别计数, 不合并。"""
    m = MemoryManager()
    for _ in range(3):
        m.save_fact("preference", "重复内容")
    m.save_fact("history", "重复内容")

    pref_top = m.top_frequent(category="preference", min_count=1)
    hist_top = m.top_frequent(category="history", min_count=1)
    assert pref_top and hist_top
    assert pref_top[0] == ("重复内容", 3)
    assert hist_top[0] == ("重复内容", 1)


def test_recent_and_count(repo_root):
    m = MemoryManager()
    n_before = m.count()
    for i in range(3):
        m.save_fact("note", f"item {i}")
    assert m.count() == n_before + 3
    last = m.recent(n=2)
    assert len(last) == 2
    assert all(isinstance(f.content, str) for f in last)


def test_recall_by_turn_idx(repo_root):
    """5.1 新方法: 按 turn 整数索引召回, 走 idx_facts_source_turn_idx。"""
    m = MemoryManager()
    m.save_fact("note", "t0 fact A", source_turn="t0", source_turn_idx=0)
    m.save_fact("note", "t0 fact B", source_turn="t0", source_turn_idx=0)
    m.save_fact("note", "t2 fact", source_turn="t2", source_turn_idx=2)
    # 没填 idx 的不参与按 idx 召回
    m.save_fact("note", "无 idx 的 fact", source_turn="t?")

    turn0 = m.recall_by_turn_idx(0)
    contents0 = {x.content for x in turn0}
    assert contents0 == {"t0 fact A", "t0 fact B"}
    assert all(x.source_turn_idx == 0 for x in turn0)

    turn2 = m.recall_by_turn_idx(2)
    assert len(turn2) == 1
    assert turn2[0].content == "t2 fact"
    assert turn2[0].source_turn_idx == 2

    # 不存在的 turn_idx 返回空 (不是 None)
    empty = m.recall_by_turn_idx(999)
    assert empty == []


def test_schema_v51_migration_idempotent(repo_root):
    """5.1 migration: 反复 init 不应破坏, 也不应重复加列。"""
    m1 = MemoryManager()
    cols1 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert "source_turn_idx" in cols1

    # 模拟老 DB (没 source_turn_idx) 升级路径: 手工删列不现实,
    # 但我们可以直接验证 _migrate_v51 在已有列上 no-op
    m1._migrate_v51()  # 第二次调用不应抛
    cols2 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert cols2.count("source_turn_idx") == 1  # 没有被加第二遍

    # 索引存在性
    idx = [r[1] for r in m1._conn.execute("PRAGMA index_list(facts)").fetchall()]
    assert "idx_facts_source_turn_idx" in idx
    m1.close()


# === 5.2 新方法测试 ===

def test_delete_by_turn_idx_removes_matching_rows(repo_root):
    """5.2: delete_by_turn_idx 删除该 turn 的全部 fact 并返回删除条数。"""
    m = MemoryManager()
    m.save_fact("note", "t5 A", source_turn="t5", source_turn_idx=5)
    m.save_fact("note", "t5 B", source_turn="t5", source_turn_idx=5)
    m.save_fact("note", "t6 keep", source_turn="t6", source_turn_idx=6)

    deleted = m.delete_by_turn_idx(5)
    assert deleted == 2

    # t5 已删空; t6 保留
    assert m.recall_by_turn_idx(5) == []
    survivors = m.recall_by_turn_idx(6)
    assert len(survivors) == 1
    assert survivors[0].content == "t6 keep"


def test_delete_by_turn_idx_missing_returns_zero(repo_root):
    """5.2: 不存在的 turn_idx 不抛异常, 返回 0。"""
    m = MemoryManager()
    m.save_fact("note", "only t7", source_turn="t7", source_turn_idx=7)
    # 不存在的 turn_idx
    assert m.delete_by_turn_idx(404) == 0
    # 现有数据未受影响
    assert len(m.recall_by_turn_idx(7)) == 1


def test_delete_by_turn_idx_skips_null_idx_rows(repo_root):
    """5.2: 没填 source_turn_idx 的老行不应被误删 (NULL != ?)。"""
    m = MemoryManager()
    m.save_fact("note", "无 idx", source_turn="t?")  # source_turn_idx=None
    m.save_fact("note", "有 idx", source_turn="t8", source_turn_idx=8)

    deleted = m.delete_by_turn_idx(0)  # 0 不会匹配 NULL
    assert deleted == 0

    # 两条都还在
    assert m.count() == 2
    assert len(m.recall_by_turn_idx(8)) == 1

# === 5.3 新方法 + 新字段测试 ===

def test_priority_field_persists(repo_root):
    """5.3: Fact dataclass 加 priority 字段, save/recall 持久化。"""
    m = MemoryManager()
    f = m.save_fact(
        "preference", "user 喜欢简洁", source_turn="t10",
        source_turn_idx=10, priority=3,
    )
    assert f.priority == 3

    hits = m.recall("简洁")
    assert hits and hits[0].priority == 3


def test_save_fact_priority_default_is_zero(repo_root):
    """5.3: 不传 priority 时默认 0, recall_high_priority 默认不召回。"""
    m = MemoryManager()
    f = m.save_fact("note", "默认 priority")
    assert f.priority == 0


def test_recall_high_priority_orders_by_priority_then_ts(repo_root):
    """5.3: recall_high_priority 按 priority DESC, ts DESC 排序。"""
    m = MemoryManager()
    # priority=5 在 t1 写入
    f1 = m.save_fact("note", "high first", source_turn="t1", source_turn_idx=1, priority=5)
    # priority=5 但后写 — 应排在前一条之后 (ts DESC)
    f2 = m.save_fact("note", "high later", source_turn="t2", source_turn_idx=2, priority=5)
    # priority=3 — 排在两个 5 之后
    f3 = m.save_fact("note", "mid", source_turn="t3", source_turn_idx=3, priority=3)
    # priority=0 — 默认行, 不应出现
    m.save_fact("note", "default", source_turn="t4", source_turn_idx=4)

    hits = m.recall_high_priority(k=10)
    contents = [h.content for h in hits]
    # priority=5 两条在前, priority=3 第三, priority=0 不在
    assert contents == ["high later", "high first", "mid"]


def test_recall_high_priority_min_priority_excludes_default(repo_root):
    """5.3: min_priority=1 默认排除 priority=0 行; min_priority=0 召回全部。"""
    m = MemoryManager()
    m.save_fact("note", "p=5 row", priority=5)
    m.save_fact("note", "p=3 row", priority=3)
    m.save_fact("note", "p=0 row")  # 默认

    # 默认 min_priority=1: 只召回 p>=1
    hits = m.recall_high_priority(k=10)
    assert {h.content for h in hits} == {"p=5 row", "p=3 row"}

    # 显式 min_priority=0: 召回全部
    all_hits = m.recall_high_priority(k=10, min_priority=0)
    assert {h.content for h in all_hits} == {"p=5 row", "p=3 row", "p=0 row"}


def test_recall_high_priority_with_category(repo_root):
    """5.3: 传 category 时走 idx_facts_category_priority_ts 复合索引。"""
    m = MemoryManager()
    m.save_fact("preference", "p high A", priority=5)
    m.save_fact("preference", "p high B", priority=3)
    m.save_fact("history", "h high", priority=5)  # 不同 category

    hits = m.recall_high_priority(k=10, category="preference")
    contents = [h.content for h in hits]
    assert "h high" not in contents
    assert contents == ["p high A", "p high B"]
    assert all(h.category == "preference" for h in hits)


def test_recall_high_priority_respects_k_limit(repo_root):
    """5.3: k 限制条数, 多余的 priority 高行不会被召回。"""
    m = MemoryManager()
    for i in range(5):
        m.save_fact("note", f"p=5 row {i}", priority=5)
    hits = m.recall_high_priority(k=3)
    assert len(hits) == 3
    assert all(h.priority == 5 for h in hits)


def test_schema_v53_migration_idempotent(repo_root):
    """5.3 migration: 反复 init 不应破坏, priority 列不会被重复加。"""
    m1 = MemoryManager()
    cols1 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert "priority" in cols1

    # 第二次调用不应抛, 也不应再加列
    m1._migrate_v53()
    cols2 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert cols2.count("priority") == 1

    # 索引存在
    idx = [r[1] for r in m1._conn.execute("PRAGMA index_list(facts)").fetchall()]
    assert "idx_facts_category_priority_ts" in idx
    m1.close()

# === 5.5 新方法 + 新字段测试 ===

def test_archived_field_default_false(repo_root):
    """5.5: Fact.archived 默认 False (新行可见)."""
    m = MemoryManager()
    f = m.save_fact("note", "默认 archived")
    assert f.archived is False
    # 落库后 recall 出来也应一致
    hits = m.recall("默认 archived")
    assert hits and hits[0].archived is False


def test_archive_fact_marks_row(repo_root):
    """5.5: archive_fact(id) 标 archived=1, 返回 True."""
    m = MemoryManager()
    f = m.save_fact("note", "待归档 fact")
    assert m.archive_fact(f.id) is True
    # recall 仍能召回 (兼容: 老方法不过滤 archived)
    hits = m.recall("待归档")
    assert hits and hits[0].archived is True


def test_archive_fact_is_idempotent_and_safe(repo_root):
    """5.5: 重复 archive 返回 False; 不存在的 id 返回 False; 不抛."""
    m = MemoryManager()
    f = m.save_fact("note", "once")
    # 第一次 archive → True
    assert m.archive_fact(f.id) is True
    # 第二次 archive → False (幂等)
    assert m.archive_fact(f.id) is False
    # 不存在的 id → False
    assert m.archive_fact(999999) is False


def test_unarchive_fact_restores_row(repo_root):
    """5.5: unarchive_fact 把 archived=1 恢复为 0."""
    m = MemoryManager()
    f = m.save_fact("note", "归档再恢复")
    m.archive_fact(f.id)
    assert m.unarchive_fact(f.id) is True
    # 重复 unarchive → False (幂等)
    assert m.unarchive_fact(f.id) is False


def test_recall_active_excludes_archived(repo_root):
    """5.5: recall_active 默认排除 archived=1 行."""
    m = MemoryManager()
    keep = m.save_fact("note", "active fact")
    gone = m.save_fact("note", "archived fact")
    m.archive_fact(gone.id)

    hits = m.recall_active(k=10)
    contents = {h.content for h in hits}
    assert "active fact" in contents
    assert "archived fact" not in contents
    # keep 行仍 archived=False
    keep_hit = [h for h in hits if h.id == keep.id][0]
    assert keep_hit.archived is False
    # gone 行不在结果里 (无法直接断言, 但已通过 contents 集合验证)


def test_recall_active_with_query_and_category(repo_root):
    """5.5: recall_active 支持 query + category 过滤."""
    m = MemoryManager()
    m.save_fact("preference", "user 喜欢 Python")
    m.save_fact("history", "user 写过 C++")
    pref_archived = m.save_fact("preference", "user 喜欢 Rust")
    m.archive_fact(pref_archived.id)

    # category + query 协同过滤
    hits = m.recall_active(query="user", k=10, category="preference")
    contents = {h.content for h in hits}
    assert "user 喜欢 Python" in contents
    assert "user 喜欢 Rust" not in contents  # archived
    assert all(h.category == "preference" for h in hits)


def test_count_active_skips_archived(repo_root):
    """5.5: count_active 只算 archived=0 行; count() 仍算全部."""
    m = MemoryManager()
    n0 = m.count()
    n0a = m.count_active()
    a = m.save_fact("note", "A")
    b = m.save_fact("note", "B")
    assert m.count() == n0 + 2
    assert m.count_active() == n0a + 2
    m.archive_fact(a.id)
    assert m.count() == n0 + 2         # 不变 (软删不丢行)
    assert m.count_active() == n0a + 1 # 只剩 B


def test_schema_v55_migration_idempotent(repo_root):
    """5.5 migration: 反复 init 不应破坏, archived 列不会被重复加."""
    m1 = MemoryManager()
    cols1 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert "archived" in cols1

    # 第二次调用不应抛, 也不应再加列
    m1._migrate_v55()
    cols2 = [r[1] for r in m1._conn.execute("PRAGMA table_info(facts)").fetchall()]
    assert cols2.count("archived") == 1

    # partial index 存在 (sqlite_master 查)
    idx_rows = m1._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_facts_active'"
    ).fetchall()
    assert idx_rows and idx_rows[0][0] == "idx_facts_active"
    m1.close()
