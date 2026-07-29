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