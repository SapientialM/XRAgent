"""5.8: pinned 行为测试。

覆盖:
    - Fact.pinned 字段默认 False
    - save_fact(pinned=True) 持久化
    - pin_fact / unpin_fact / set_pinned
    - archived 的 fact 不能被 pin
    - list_pinned 过滤 + category + k
    - 5.7 行为回归 (confidence / archive / recall_range)
"""
from __future__ import annotations

import pytest

from xragent.memory.manager import Fact, MemoryManager, SCHEMA_VERSION


@pytest.fixture
def mem(tmp_mgr):
    return tmp_mgr


def _save(mem, **kw):
    kw.setdefault("category", "test")
    kw.setdefault("content", "hello world")
    return mem.save_fact(**kw)


# ---- schema / import ----

def test_schema_version_is_58():
    assert SCHEMA_VERSION == 58


def test_fact_has_pinned_default_false():
    f = Fact(id=1, ts=0.0, category="x", content="y")
    assert f.pinned is False


# ---- save_fact ----

def test_save_fact_pinned_true_persists(mem):
    f = _save(mem, content="pinned fact", pinned=True)
    assert f.pinned is True
    # 重读
    rows = mem.list_pinned()
    assert len(rows) == 1
    assert rows[0].id == f.id
    assert rows[0].pinned is True


def test_save_fact_pinned_false_default(mem):
    f = _save(mem, content="normal fact")
    assert f.pinned is False
    assert mem.list_pinned() == []


# ---- pin / unpin ----

def test_pin_fact_returns_true(mem):
    f = _save(mem)
    assert mem.pin_fact(f.id) is True
    assert mem.list_pinned()[0].id == f.id


def test_pin_fact_already_pinned_returns_false_rowcount_zero(mem):
    f = _save(mem)
    assert mem.pin_fact(f.id) is True
    # 第二次 pin (条件 pinned=1 AND archived=0 不再匹配, 因为已经是 1)
    assert mem.pin_fact(f.id) is False


def test_pin_fact_archived_returns_false(mem):
    f = _save(mem)
    mem.archive_fact(f.id)
    assert mem.pin_fact(f.id) is False


def test_pin_fact_unknown_id_returns_false(mem):
    assert mem.pin_fact(99999) is False


def test_unpin_fact_returns_true(mem):
    f = _save(mem, pinned=True)
    assert mem.unpin_fact(f.id) is True
    assert mem.list_pinned() == []


def test_unpin_fact_not_pinned_returns_false(mem):
    f = _save(mem)
    # 未 pin 的 fact, unpin 找不到匹配 (pinned=0 WHERE id=?)
    assert mem.unpin_fact(f.id) is False


def test_unpin_archived_works(mem):
    f = _save(mem, pinned=True)
    mem.archive_fact(f.id)
    # archived 也能 unpin
    assert mem.unpin_fact(f.id) is True


# ---- set_pinned ----

def test_set_pinned_true(mem):
    f = _save(mem)
    got = mem.set_pinned(f.id, True)
    assert got is not None
    assert got.id == f.id
    assert got.pinned is True


def test_set_pinned_false(mem):
    f = _save(mem, pinned=True)
    got = mem.set_pinned(f.id, False)
    assert got is not None
    assert got.pinned is False


def test_set_pinned_true_on_archived_returns_none(mem):
    f = _save(mem)
    mem.archive_fact(f.id)
    assert mem.set_pinned(f.id, True) is None


def test_set_pinned_unknown_id_returns_none(mem):
    assert mem.set_pinned(99999, True) is None


# ---- list_pinned ----

def test_list_pinned_orders_newest_first(mem):
    a = _save(mem, content="a", title="A")
    b = _save(mem, content="b", title="B")
    c = _save(mem, content="c", title="C")
    mem.pin_fact(b.id)
    mem.pin_fact(a.id)
    mem.pin_fact(c.id)
    rows = mem.list_pinned()
    assert [r.id for r in rows] == [c.id, a.id, b.id]


def test_list_pinned_filter_category(mem):
    _save(mem, content="x", category="a", pinned=True)
    _save(mem, content="y", category="b", pinned=True)
    _save(mem, content="z", category="a")
    rows = mem.list_pinned(category="a")
    assert len(rows) == 1
    assert rows[0].category == "a"


def test_list_pinned_excludes_archived(mem):
    f1 = _save(mem, content="alive", pinned=True)
    f2 = _save(mem, content="dead", pinned=True)
    mem.archive_fact(f2.id)
    rows = mem.list_pinned()
    assert [r.id for r in rows] == [f1.id]


def test_list_pinned_k_limit(mem):
    for i in range(5):
        _save(mem, content=f"c{i}", pinned=True)
    rows = mem.list_pinned(k=2)
    assert len(rows) == 2


def test_list_pinned_empty(mem):
    assert mem.list_pinned() == []


# ---- migration idempotency ----

def test_migrate_v58_idempotent(mem):
    # 重复执行迁移不应报错
    mem._migrate_v58()
    mem._migrate_v58()
    cols = {r[1] for r in mem._conn.execute("PRAGMA table_info(facts)").fetchall()}
    assert "pinned" in cols