"""MemoryManager：SQLite 事实存取。"""
from __future__ import annotations

import time

from xragent.memory.manager import MemoryManager


def test_save_and_recall(repo_root):
    m = MemoryManager()
    fid = m.save_fact("preference", "user 喜欢 Python", source_turn="t1")
    assert fid > 0
    results = m.recall("Python")
    assert any(f.id == fid for f in results)
    assert any(f.content == "user 喜欢 Python" for f in results)


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