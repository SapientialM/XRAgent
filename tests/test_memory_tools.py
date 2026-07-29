"""memory 工具层：memory_recall_range / memory_top_frequent / registry 注册。

底层 MemoryManager 在 tests/test_memory.py 已覆盖, 本文件聚焦"工具层 wrapper 是否
正确暴露给 LLM agent 调用"。
"""
from __future__ import annotations

import time

from xragent.tools.memory_tools import memory_recall_range, memory_top_frequent


def test_memory_recall_range_filters_by_window(repo_root):
    """memory_recall_range 应只返回时间窗口内的 fact。"""
    from xragent.memory.manager import MemoryManager

    m = MemoryManager()
    t0 = time.time()
    m.save_fact("note", "earlier fact")
    time.sleep(0.05)
    t_mid = time.time()
    time.sleep(0.05)
    m.save_fact("note", "middle fact")
    time.sleep(0.05)
    m.save_fact("note", "later fact")

    # 只取 t_mid 之后 -> 只剩 "later fact"
    out = memory_recall_range(start_ts=t_mid)
    assert out["ok"] is True
    assert out["count"] == 1
    assert "later" in out["facts"][0]["content"]

    # 取 [t0, t_mid] -> 只剩 "earlier fact"
    out = memory_recall_range(start_ts=t0, end_ts=t_mid)
    assert out["count"] == 1
    assert "earlier" in out["facts"][0]["content"]

    # 开放端: 不传 start_ts/end_ts 应召回全部
    out = memory_recall_range()
    assert out["count"] >= 3


def test_memory_recall_range_with_category(repo_root):
    """category 应正确过滤。"""
    from xragent.memory.manager import MemoryManager

    m = MemoryManager()
    m.save_fact("preference", "user 喜欢 Python")
    m.save_fact("history", "user 写过 C++")

    pref = memory_recall_range(category="preference")
    assert pref["count"] >= 1
    assert all(f["category"] == "preference" for f in pref["facts"])

    hist = memory_recall_range(category="history")
    assert all(f["category"] == "history" for f in hist["facts"])


def test_memory_top_frequent_returns_ranked(repo_root):
    """memory_top_frequent 应按次数降序, min_count 应过滤噪音。"""
    from xragent.memory.manager import MemoryManager

    m = MemoryManager()
    for _ in range(3):
        m.save_fact("preference", "user 喜欢简洁")
    for _ in range(2):
        m.save_fact("preference", "user 喜欢 Rust")
    m.save_fact("preference", "noise one-off")

    out = memory_top_frequent(n=5, category="preference", min_count=2)
    assert out["ok"] is True
    contents = [item["content"] for item in out["top"]]
    assert "user 喜欢简洁" in contents
    assert "noise one-off" not in contents  # min_count=2 过滤掉一次性

    # 排序: 3 次应排在 2 次之前
    counts = {item["content"]: item["count"] for item in out["top"]}
    rank = {item["content"]: i for i, item in enumerate(out["top"])}
    assert counts["user 喜欢简洁"] == 3
    assert counts["user 喜欢 Rust"] == 2
    assert rank["user 喜欢简洁"] < rank["user 喜欢 Rust"]


def test_memory_top_frequent_min_count_one_includes_oneoffs(repo_root):
    """min_count=1 时, 一次性 fact 也应进入 top（与 min_count=2 默认行为对比）。

    这是 default min_count=2 那个测试的镜像边界, 锁定"不过滤"路径不退化:
    - min_count=1: 所有 fact 都在
    - min_count=2: 一次性被过滤
    同时验证 count 字段等于实际返回的 top 长度（不是 n）。
    """
    from xragent.memory.manager import MemoryManager

    m = MemoryManager()
    m.save_fact("note", "recurring thought")  # 重复 2 次
    m.save_fact("note", "recurring thought")
    m.save_fact("note", "rare one-off")        # 一次性

    # min_count=1: 全部进入 top
    out1 = memory_top_frequent(n=10, category="note", min_count=1)
    contents1 = {item["content"] for item in out1["top"]}
    assert "rare one-off" in contents1
    assert "recurring thought" in contents1
    assert out1["count"] == 2  # 两种 distinct content
    # 排序: 2 次应在 1 次之前
    cnt1 = {item["content"]: item["count"] for item in out1["top"]}
    assert cnt1["recurring thought"] == 2
    assert cnt1["rare one-off"] == 1

    # min_count=2: 一次性被过滤
    out2 = memory_top_frequent(n=10, category="note", min_count=2)
    contents2 = {item["content"] for item in out2["top"]}
    assert "rare one-off" not in contents2
    assert "recurring thought" in contents2
    assert out2["count"] == 1

    # 空库场景: 无任何 fact 时应返回空 list, ok=True, count=0
    m_empty = MemoryManager()
    # 复用同一 DB 路径会拿到上面的 fact, 所以这次走不同 category 来确保 0 命中
    out_empty = memory_top_frequent(n=10, category="non-existent-category", min_count=1)
    assert out_empty["ok"] is True
    assert out_empty["top"] == []
    assert out_empty["count"] == 0


def test_new_tools_registered_in_default_registry(repo_root):
    """两个新工具应注册到默认 registry, 且 risk=low。"""
    from xragent.tools.registry import build_default_registry

    r = build_default_registry()
    assert "memory_recall_range" in r.names()
    assert "memory_top_frequent" in r.names()

    spec_rr = r.get("memory_recall_range")
    assert spec_rr.risk == "low"
    assert "start_ts" in spec_rr.input_schema["properties"]
    assert "end_ts" in spec_rr.input_schema["properties"]

    spec_tf = r.get("memory_top_frequent")
    assert spec_tf.risk == "low"
    assert "n" in spec_tf.input_schema["properties"]
    assert "min_count" in spec_tf.input_schema["properties"]

    # 可调用
    out = r.run("memory_recall_range", {})
    assert out["ok"] is True
    assert "facts" in out
