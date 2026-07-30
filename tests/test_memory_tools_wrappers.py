"""memory 工具层 wrapper 边界测试。

与 tests/test_memory_tools.py 互补 —— 那里聚焦"主路径 + registry 注册",
本文件聚焦 wrapper 形状与透传边界, 防止 LLM-facing JSON 输出形态退化。
"""
from __future__ import annotations

import json

from xragent.memory.manager import MemoryManager
from xragent.tools.memory_tools import (
    memory_recall_by_tag,
    memory_recall_range,
    memory_top_frequent,
)


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


# === memory_recall_by_tag wrapper 测试 ===
# 5.4: tags JSON 数组; recall_by_tag 是底层 manager 方法,
# 但 5.4→5.5 一直缺 LLM-facing wrapper。本组测试锁定 wrapper 形状与边界。


def test_recall_by_tag_basic_returns_matching_fact(repo_root):
    """存一条带 tag 的 fact, recall_by_tag 应召回, count=1。"""
    m = MemoryManager()
    f = m.save_fact(
        "preference", "user 喜欢简洁", tags=["style", "preference"]
    )

    out = memory_recall_by_tag(tag="style", k=10)
    assert out["ok"] is True
    assert out["count"] == 1
    assert len(out["facts"]) == 1
    hit = out["facts"][0]
    assert hit["id"] == f.id
    assert hit["content"] == "user 喜欢简洁"
    assert hit["category"] == "preference"


def test_recall_by_tag_facts_include_tags_field(repo_root):
    """本工具特有: facts 应额外含 ``tags`` 字段 (list[str]),
    让 LLM 看到命中行上的其它 tag (可能触发链式查询)。

    前 4 个键 (id/ts/category/content) 顺序与 _fact_to_dict 锁定,
    ``tags`` 后置方便 LLM 解析时不与既有契约冲突。
    """
    m = MemoryManager()
    m.save_fact("note", "A", tags=["alpha", "beta"])
    m.save_fact("note", "B", tags=["alpha"])  # 也带 alpha

    out = memory_recall_by_tag(tag="alpha", k=10)
    assert out["count"] == 2
    for hit in out["facts"]:
        # 字段顺序锁定
        assert list(hit.keys())[:4] == ["id", "ts", "category", "content"]
        # tags 必须是 list[str], 不是底层 manager 引用
        assert isinstance(hit["tags"], list)
        assert all(isinstance(t, str) for t in hit["tags"])
        assert "alpha" in hit["tags"]
    # B 只有 alpha, A 有 alpha+beta —— 验证 tags 没被截断
    a_hit = [h for h in out["facts"] if h["content"] == "A"][0]
    assert set(a_hit["tags"]) == {"alpha", "beta"}
    b_hit = [h for h in out["facts"] if h["content"] == "B"][0]
    assert b_hit["tags"] == ["alpha"]


def test_recall_by_tag_cross_category(repo_root):
    """tag 召回跨 category 横向 (与其它 3 个 recall 工具的核心差异)。"""
    m = MemoryManager()
    m.save_fact("preference", "p1", tags=["shared"])
    m.save_fact("history", "h1", tags=["shared"])
    m.save_fact("note", "n1", tags=["other"])  # 不应被召回

    out = memory_recall_by_tag(tag="shared", k=10)
    contents = {h["content"] for h in out["facts"]}
    assert contents == {"p1", "h1"}
    cats = {h["category"] for h in out["facts"]}
    assert cats == {"preference", "history"}


def test_recall_by_tag_empty_tag_returns_zero_count(repo_root):
    """tag 为空字符串 / None 时 wrapper 早返 (不查 DB)。

    底层 manager 也会拦截 LIKE '%%', 但 wrapper 早返能避免一次
    无意义的 DB 往返, 并让 LLM 拿到稳定的 "空结果" 形状。
    """
    m = MemoryManager()
    m.save_fact("note", "should not be returned", tags=["x"])

    for bad in ("", None):  # type: ignore[arg-type]
        out = memory_recall_by_tag(tag=bad)  # type: ignore[arg-type]
        assert out["ok"] is True
        assert out["count"] == 0
        assert out["facts"] == []


def test_recall_by_tag_no_match_returns_zero(repo_root):
    """无命中: ok=True, count=0, facts=[] (与 memory_recall_range 对齐)。"""
    m = MemoryManager()
    m.save_fact("note", "tagged", tags=["alpha"])

    out = memory_recall_by_tag(tag="nonexistent-tag-xyz", k=10)
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["facts"] == []


def test_recall_by_tag_k_clip_low(repo_root):
    """k=0 / 负数会被 _clip_limit 夹到 1, 不返回空。"""
    m = MemoryManager()
    m.save_fact("note", "f1", tags=["x"])
    m.save_fact("note", "f2", tags=["x"])

    for bad_k in (0, -5, -100):
        out = memory_recall_by_tag(tag="x", k=bad_k)
        # k 兜底后是 1, 但库内有 2 条 ts DESC, 应返回 1 条
        assert out["count"] == 1
        assert len(out["facts"]) == 1


def test_recall_by_tag_k_clip_high(repo_root):
    """k=2000 会被 _clip_limit 夹到 1000, 库内只有 3 条应原样返回。"""
    m = MemoryManager()
    for i in range(3):
        m.save_fact("note", f"f{i}", tags=["x"])

    out = memory_recall_by_tag(tag="x", k=2000)
    # 兜底后 k=1000, 库内 3 条全部返回
    assert out["count"] == 3
    assert len(out["facts"]) == 3


def test_recall_by_tag_unicode_tag(repo_root):
    """中文 / emoji tag 也应命中 (LIKE 模式大小写敏感, 但 unicode 透明)。"""
    m = MemoryManager()
    m.save_fact("note", "中文 tag", tags=["中文", "🎯"])
    m.save_fact("note", "emoji tag", tags=["🎯"])

    out = memory_recall_by_tag(tag="中文", k=10)
    assert out["count"] == 1
    assert out["facts"][0]["content"] == "中文 tag"

    out2 = memory_recall_by_tag(tag="🎯", k=10)
    assert out2["count"] == 2


def test_recall_by_tag_is_json_serializable(repo_root):
    """输出可直接 json.dumps (LLM 工具路径强约束)。"""
    m = MemoryManager()
    m.save_fact("note", "jsonable", tags=["t"])

    out = memory_recall_by_tag(tag="t", k=10)
    json.dumps(out)  # 不抛 = 通过