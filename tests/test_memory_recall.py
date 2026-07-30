"""memory_recall 工具层测试（关键词 LIKE 召回）。

设计原则:
    - 不依赖 build_default_registry()，避开 evolve_tools 预存 import 问题。
    - 直接 import memory_tools 与 registry 的 ToolRegistry 类。
    - 覆盖: 关键词命中 / category 过滤 / 空 query 退化 / k 透传 / 边界 / JSON 序列化。
"""
from __future__ import annotations

import json

from xragent.memory.manager import MemoryManager
from xragent.tools import memory_tools
from xragent.tools.memory_tools import memory_recall


def test_recall_keyword_hit(repo_root):
    """关键词应能命中; 多个命中按 ts DESC。"""
    m = MemoryManager()
    m.save_fact("note", "user 喜欢 Python")
    m.save_fact("note", "user 写过 Rust")
    m.save_fact("note", "Python 是动态语言")

    out = memory_recall(query="Python")
    assert out["ok"] is True
    assert out["count"] == 2
    # 两条都应含 Python
    for f in out["facts"]:
        assert "Python" in f["content"]


def test_recall_no_hit_returns_empty(repo_root):
    """无命中时 ok=True, count=0, facts=[]。LLM 拿到统一形状才能稳定解析。"""
    out = memory_recall(query="绝对不存在-xyz-关键词-zzz")
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["facts"] == []


def test_recall_empty_query_returns_latest(repo_root):
    """空 query 退化为全量最新 k 条。"""
    m = MemoryManager()
    for i in range(10):
        m.save_fact("note", f"item {i}")

    out = memory_recall(query="", k=3)
    assert out["ok"] is True
    assert out["count"] == 3
    # 最新写入的 3 条; 但 recall 的 ts 取 time.time() 浮点, 顺序由 SQL ORDER BY ts DESC
    # 决定, 我们不锁具体是哪 3 条, 只锁集合大小 + 都有 content
    assert all("item" in f["content"] for f in out["facts"])


def test_recall_with_category_filter(repo_root):
    """category 应正确过滤。"""
    m = MemoryManager()
    m.save_fact("preference", "Python 是首选")
    m.save_fact("history", "Python 是早期项目用的语言")

    out = memory_recall(query="Python", category="preference")
    assert out["count"] == 1
    assert out["facts"][0]["category"] == "preference"
    assert out["facts"][0]["content"] == "Python 是首选"

    # 跨类不应拿到
    out2 = memory_recall(query="Python", category="history")
    assert out2["count"] == 1
    assert out2["facts"][0]["category"] == "history"


def test_recall_k_param_respected(repo_root):
    """k 应透传到 manager; 写 5 条只取 2 应只剩 2 条。"""
    m = MemoryManager()
    for i in range(5):
        m.save_fact("note", f"item {i}")

    out = memory_recall(query="item", k=2)
    assert out["count"] == 2
    assert len(out["facts"]) == 2


def test_recall_k_clamps_zero_and_negative(repo_root):
    """k=0 / 负数 / 超大 都应被 clip 到 [1, 1000]，避免空结果或拉爆。"""
    # k=0 -> clip 到 1
    m = MemoryManager()
    m.save_fact("note", "a")
    m.save_fact("note", "b")
    out = memory_recall(query="", k=0)
    assert out["count"] == 1

    # k=-5 -> clip 到 1
    out = memory_recall(query="", k=-5)
    assert out["count"] == 1

    # k=99999 -> clip 到 1000 (但库只 2 条, count=2)
    out = memory_recall(query="", k=99999)
    assert out["count"] == 2


def test_recall_output_is_json_serializable(repo_root):
    """wrapper 返回值必须可直接 JSON 序列化（LLM 工具调用路径强约束）。"""
    m = MemoryManager()
    m.save_fact("note", "json 序列化测试")

    out = memory_recall(query="json")
    json.dumps(out)  # 不能 raise


def test_recall_fact_shape_includes_required_keys(repo_root):
    """每条 fact 应含 id/ts/category/content 四键，LLM 强契约。"""
    m = MemoryManager()
    m.save_fact("note", "shape test")

    out = memory_recall(query="shape")
    assert out["count"] >= 1
    f = out["facts"][0]
    for key in ("id", "ts", "category", "content"):
        assert key in f, f"missing key: {key}"
    assert isinstance(f["id"], int)
    assert isinstance(f["ts"], (int, float))
    assert isinstance(f["category"], str)
    assert isinstance(f["content"], str)


def test_recall_module_attr_is_callable(repo_root):
    """memory_tools.memory_recall 必须存在且 callable。"""
    assert hasattr(memory_tools, "memory_recall")
    assert callable(memory_recall)


def test_recall_in_registry_when_importable(repo_root):
    """memory_recall 应注册到默认 registry（仅当 evolve_tools 能 import 时）。

    evolve_tools 预存 `from ..blacklist import check` 路径错误, 导致
    build_default_registry() 在某些环境抛 ModuleNotFoundError。这是仓库
    历史 bug, 与本工具无关; 这里用 try/except 软断言: 能 import 就验证
    注册, 不能 import 就 skip, 不让本测试的失败掩盖工具实现本身的问题。
    """
    try:
        from xragent.tools.registry import build_default_registry
        r = build_default_registry()
    except ModuleNotFoundError as e:
        import pytest
        pytest.skip(f"build_default_registry() 预存 import 错误: {e}")
    assert "memory_recall" in r.names()
    spec = r.get("memory_recall")
    assert spec.risk == "low"
    # schema 必含三个字段
    props = spec.input_schema["properties"]
    assert "query" in props
    assert "k" in props
    assert "category" in props

    # 可调用
    out = r.run("memory_recall", {"query": "绝不存在的关键词-zzz"})
    assert out["ok"] is True
    assert out["count"] == 0
