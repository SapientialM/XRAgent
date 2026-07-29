"""memory 工具层 wrapper 边界测试。

与 tests/test_memory_tools.py 互补 —— 那里聚焦"主路径 + registry 注册",
本文件聚焦 wrapper 形状与透传边界, 防止 LLM-facing JSON 输出形态退化。
"""
from __future__ import annotations

import json

from xragent.memory.manager import MemoryManager
from xragent.tools.memory_tools import memory_recall_range, memory_top_frequent


def test_wrapper_outputs_are_json_serializable(repo_root):
    """wrapper 返回值必须可直接 JSON 序列化（LLM 工具调用路径强约束）。"""
    m = MemoryManager()
    m.save_fact("note", "json serializable fact")

    rr = memory_recall_range()
    json.dumps(rr)  # 不能 raise

    tf = memory_top_frequent(n=5, category="note", min_count=1)
    json.dumps(tf)


def test_recall_range_respects_k_param(repo_root):
    """k 参数应透传到 manager; 写 5 条只取 2 应只剩 2 条。"""
    m = MemoryManager()
    for i in range(5):
        m.save_fact("note", f"item {i}")

    out = memory_recall_range(k=2)
    assert out["count"] == 2
    assert len(out["facts"]) == 2


def test_top_frequent_returns_count_matches_len(repo_root):
    """count 字段必须等于 top 实际长度（不是 n 参数）。"""
    m = MemoryManager()
    m.save_fact("note", "unique")

    # min_count=1 拿全部, 但库内只有 1 条 distinct content
    out = memory_top_frequent(n=10, category="note", min_count=1)
    assert out["count"] == 1
    assert len(out["top"]) == 1
    assert out["top"][0]["content"] == "unique"
    assert out["top"][0]["count"] == 1


def test_top_frequent_min_count_filters_at_wrapper_layer(repo_root):
    """min_count=2 时, 一次性 fact 不应在 top 里。"""
    m = MemoryManager()
    m.save_fact("note", "twice")
    m.save_fact("note", "twice")
    m.save_fact("note", "once")

    out = memory_top_frequent(n=10, category="note", min_count=2)
    contents = [item["content"] for item in out["top"]]
    assert "twice" in contents
    assert "once" not in contents
    assert out["count"] == 1


def test_recall_range_empty_db_returns_zero_count(repo_root):
    """空库场景: ok=True, count=0, facts=[]。

    不抛异常、不返回 None —— LLM 拿到统一形状才能稳定解析。
    """
    # 用一个不存在的 category 拿到 0 命中
    out = memory_recall_range(category="definitely-empty-category-xyz")
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["facts"] == []
