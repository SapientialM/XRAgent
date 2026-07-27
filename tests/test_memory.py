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


def test_recall_by_category(repo_root):
    m = MemoryManager()
    m.save_fact("a", "alpha")
    m.save_fact("b", "beta")
    m.save_fact("a", "alpha2")
    only_a = m.recall("", category="a")
    assert len(only_a) == 2
    assert all(f.category == "a" for f in only_a)


def test_recent_orders_desc(repo_root):
    m = MemoryManager()
    for i in range(5):
        m.save_fact("seq", f"item-{i}")
        time.sleep(0.005)
    recent = m.recent(3)
    assert len(recent) == 3
    # 最近插入的应该排前面
    assert recent[0].content == "item-4"
    assert recent[2].content == "item-2"


def test_count(repo_root):
    m = MemoryManager()
    assert m.count() == 0
    m.save_fact("x", "1")
    m.save_fact("x", "2")
    assert m.count() == 2


def test_persistence_across_instances(repo_root):
    m1 = MemoryManager()
    m1.save_fact("persist", "跨实例数据")
    m2 = MemoryManager()
    assert m2.count() >= 1
    assert any("跨实例" in f.content for f in m2.recent(5))
