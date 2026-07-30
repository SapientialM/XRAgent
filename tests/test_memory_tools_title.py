"""memory 工具 title 系列 wrapper 测试 (5.5+)。

覆盖 :func:`memory_recall_by_title` 与 :func:`memory_update_title` 两个
新增 wrapper 的形状 / 边界 / 失败回执。与 :mod:`test_memory_tools_wrappers`
同风格: 锁定 LLM-facing JSON 形状, 防 wrapper 退化。
"""
from __future__ import annotations

import json

import pytest

from xragent.memory.manager import MemoryManager
from xragent.tools import memory_tools
from xragent.tools.memory_tools import (
    _parse_fact_id,
    _validate_title,
    memory_recall_by_title,
    memory_update_title,
)


# === _parse_fact_id / _validate_title 单元测试 ===
# 这两个 helper 是 wrapper 的"前置门", LLM 传过来的 fact_id / new_title
# 必须先过它们才会落 DB。先单测, 再测 wrapper 集成行为。


@pytest.mark.parametrize(
    "value, expected",
    [
        (1, 1),
        (42, 42),
        ("42", 42),
        (42.0, 42),
        (0, 1),  # clip 到 _FACT_ID_MIN
        (-7, 1),
        (10**18, 10**18),  # clip 到 _FACT_ID_MAX
    ],
)
def test_parse_fact_id_accepts_coercible(value, expected):
    """int / 数字字符串 / 浮点 → clip 后 int; 0 / 负数 → clip 到 1。"""
    assert _parse_fact_id(value) == expected


@pytest.mark.parametrize("bad", [None, True, False, "abc", [], {}, object()])
def test_parse_fact_id_rejects_non_coercible(bad):
    """None / bool / 不可解析字符串 / 容器 / 任意对象 → 返回 None。

    不可解析值一律 None (调用方 wrap 成 ok=False), 而非抛异常, 避免
    LLM 工具调用路径出现 500。
    """
    assert _parse_fact_id(bad) is None


def test_parse_fact_id_rejects_bool():
    """``True`` / ``False`` 不是有效 fact_id, 必须返回 None 而非 1 / 0。

    ``isinstance(True, int) is True`` (bool 是 int 子类), 所以 _clip_limit
    才会单独排除 bool; _parse_fact_id 也继承这一行为, 防止 LLM 传 ``True``
    当 fact_id 走通。
    """
    assert _parse_fact_id(True) is None
    assert _parse_fact_id(False) is None


@pytest.mark.parametrize(
    "value",
    ["hello", "  spaced  ", "中文标题", "🎯"],
)
def test_validate_title_accepts_valid(value):
    """合法字符串 (含空白但非纯空白) → 返回 None (放行)。"""
    assert _validate_title(value) is None


def test_validate_title_rejects_empty_and_blank():
    """空串 / 纯空白 → 返回错误文案 (含 "空白" 字样, 方便 LLM 自检)。"""
    for bad in ("", "   ", "\n\t"):
        err = _validate_title(bad)
        assert err is not None
        assert "空白" in err


@pytest.mark.parametrize("bad", [None, 123, ["a"], {"k": "v"}, True])
def test_validate_title_rejects_non_string(bad):
    """非 str 类型 → 返回错误文案 (含 "字符串" 字样, 方便 LLM 自检)。"""
    err = _validate_title(bad)
    assert err is not None
    assert "字符串" in err


def test_validate_title_rejects_too_long():
    """长度 > 200 → 返回错误文案 (含 "200" 字样, 方便 LLM 自检)。"""
    err = _validate_title("x" * 201)
    assert err is not None
    assert "200" in err


# === memory_recall_by_title 测试 ===


def test_recall_by_title_basic_matches(repo_root):
    """存两条, 一条带 title; recall_by_title 精确等值召回。"""
    m = MemoryManager()
    titled = m.save_fact("note", "titled fact", title="alpha")
    m.save_fact("note", "untitled fact", title=None)

    out = memory_recall_by_title(title="alpha", k=10)
    assert out["ok"] is True
    assert out["count"] == 1
    assert len(out["facts"]) == 1
    hit = out["facts"][0]
    assert hit["id"] == titled.id
    assert hit["content"] == "titled fact"
    assert hit["title"] == "alpha"


def test_recall_by_title_facts_have_title_field(repo_root):
    """本工具特有: facts 末尾应含 ``title`` 字段 (str | None)。

    前 4 键 (id/ts/category/content) 顺序与 ``_fact_to_dict`` 锁定,
    ``title`` 后置, 与 ``memory_recall_by_tag`` 把 ``tags`` 后置的处理对齐。
    """
    m = MemoryManager()
    m.save_fact("note", "A", title="x")
    m.save_fact("note", "B", title=None)

    out = memory_recall_by_title(title="x", k=10)
    assert out["count"] == 1
    hit = out["facts"][0]
    # 字段顺序: id → ts → category → content → title
    assert list(hit.keys()) == ["id", "ts", "category", "content", "title"]
    assert hit["title"] == "x"


def test_recall_by_title_cross_category(repo_root):
    """精确 title 召回跨 category 横向 —— 与 ``recall_by_tag`` 行为对齐。"""
    m = MemoryManager()
    m.save_fact("preference", "p1", title="shared")
    m.save_fact("history", "h1", title="shared")
    m.save_fact("note", "n1", title="other")

    out = memory_recall_by_title(title="shared", k=10)
    contents = {h["content"] for h in out["facts"]}
    assert contents == {"p1", "h1"}
    cats = {h["category"] for h in out["facts"]}
    assert cats == {"preference", "history"}


@pytest.mark.parametrize("bad", ["", "   ", "\n", None])
def test_recall_by_title_empty_returns_zero(bad, repo_root):
    """空 / 纯空白 / ``None`` title → 早返 (不查 DB, 不抛异常)。"""
    m = MemoryManager()
    # 即便库内有 title=None 的 fact, 也不应被召回 (因为我们在 wrapper 早返)
    m.save_fact("note", "should not appear", title=None)

    out = memory_recall_by_title(title=bad, k=10)
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["facts"] == []


def test_recall_by_title_no_match_returns_zero(repo_root):
    """无命中: 形状与 memory_recall_range 对齐 (ok=True, count=0)。"""
    m = MemoryManager()
    m.save_fact("note", "titled", title="alpha")

    out = memory_recall_by_title(title="nonexistent-title-xyz", k=10)
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["facts"] == []


def test_recall_by_title_is_exact_not_substring(repo_root):
    """``title="a"`` 不应召回 ``title="alpha"`` (与 LIKE 模糊区分)。

    设计动机: title 是 fact 的命名 (一条一个), 精确等值比 LIKE 命中更窄,
    适合"修复已知某条 fact"；若 LLM 想要模糊召回应走 ``memory_recall``
    (关键词 LIKE content)。
    """
    m = MemoryManager()
    m.save_fact("note", "exact a", title="a")
    m.save_fact("note", "exact alpha", title="alpha")

    out = memory_recall_by_title(title="a", k=10)
    assert out["count"] == 1
    assert out["facts"][0]["content"] == "exact a"


@pytest.mark.parametrize("bad_k", [0, -5, -100])
def test_recall_by_title_k_clip_low(bad_k, repo_root):
    """k=0 / 负数被夹到 1, 不返回空 (与 recall_by_tag 对齐)。"""
    m = MemoryManager()
    m.save_fact("note", "f1", title="x")
    m.save_fact("note", "f2", title="x")

    out = memory_recall_by_title(title="x", k=bad_k)
    # k 兜底后是 1, 库内 2 条 ts DESC 截断到 1
    assert out["count"] == 1


def test_recall_by_title_k_clip_high(repo_root):
    """k=2000 被夹到 1000, 库内 3 条原样返回。"""
    m = MemoryManager()
    for i in range(3):
        m.save_fact("note", f"f{i}", title="x")

    out = memory_recall_by_title(title="x", k=2000)
    assert out["count"] == 3


def test_recall_by_title_unicode(repo_root):
    """中文 / emoji title 也应精确命中。"""
    m = MemoryManager()
    m.save_fact("note", "中文 fact", title="中文标题")
    m.save_fact("note", "emoji fact", title="🎯")

    out = memory_recall_by_title(title="中文标题", k=10)
    assert out["count"] == 1
    assert out["facts"][0]["content"] == "中文 fact"

    out2 = memory_recall_by_title(title="🎯", k=10)
    assert out2["count"] == 1
    assert out2["facts"][0]["content"] == "emoji fact"


def test_recall_by_title_json_serializable(repo_root):
    """输出可直接 json.dumps (LLM 工具调用路径强约束)。"""
    m = MemoryManager()
    m.save_fact("note", "j", title="t")
    out = memory_recall_by_title(title="t", k=10)
    json.dumps(out)  # 不抛 = 通过


# === memory_update_title 测试 ===


def test_update_title_basic_roundtrip(repo_root):
    """存 → update → recall_by_title 应命中新 title, 旧 title 应无命中。

    验证三件事:
      1. wrapper 返回 ok=True + updated Fact 快照
      2. DB 真的改了 (再 recall_by_title 看得到)
      3. content / category / ts 不变 (整列覆盖, 不误伤)
    """
    m = MemoryManager()
    f = m.save_fact("note", "body unchanged", title="old-name")
    orig_ts = f.ts

    out = memory_update_title(fact_id=f.id, new_title="new-name")
    assert out["ok"] is True
    assert out["id"] == f.id
    assert out["new_title"] == "new-name"
    # 5 字段 fact 快照走 _fact_to_dict_with_title
    fact_dict = out["fact"]
    assert fact_dict["id"] == f.id
    assert fact_dict["content"] == "body unchanged"  # content 不动
    assert fact_dict["category"] == "note"
    assert fact_dict["title"] == "new-name"
    assert fact_dict["ts"] == orig_ts  # ts 不动

    # 二次 recall_by_title 应能命中新 title
    out2 = memory_recall_by_title(title="new-name", k=10)
    assert out2["count"] == 1
    assert out2["facts"][0]["id"] == f.id

    # 旧 title 不应再召回 (覆盖语义)
    out3 = memory_recall_by_title(title="old-name", k=10)
    assert out3["count"] == 0


def test_update_title_strips_whitespace(repo_root):
    """wrapper 对合法 title 走 ``str.strip()`` (避免污染)。"""
    m = MemoryManager()
    f = m.save_fact("note", "x", title="old")

    out = memory_update_title(fact_id=f.id, new_title="  new-name  ")
    assert out["ok"] is True
    assert out["new_title"] == "new-name"  # stripped
    assert out["fact"]["title"] == "new-name"


def test_update_title_clears_with_none(repo_root):
    """``new_title=None`` → 清空 title (列置 NULL), 与 manager 语义对齐。

    这是 ``memory_save`` 写入时也可传的语义 ("这条 fact 没命名"); wrapper
    走 ``None`` 通道明确走 manager.update_title 的 clear 分支, 而不是
    把 "None" 字符串写进去。
    """
    m = MemoryManager()
    f = m.save_fact("note", "x", title="to-be-cleared")

    out = memory_update_title(fact_id=f.id, new_title=None)
    assert out["ok"] is True
    assert out["new_title"] is None
    assert out["fact"]["title"] is None

    # 旧 title 不应再召回
    miss = memory_recall_by_title(title="to-be-cleared", k=10)
    assert miss["count"] == 0


@pytest.mark.parametrize(
    "bad_id",
    [None, "abc", [], {}, object(), True, False],
)
def test_update_title_invalid_fact_id_returns_fail(bad_id, repo_root):
    """非法 fact_id → ok=False, error 包含 "fact_id 非法"。

    不可解析值 (None / bool / 不可解析字符串 / 容器) 一律走 ok=False,
    不抛异常, 不污染 DB。
    """
    out = memory_update_title(fact_id=bad_id, new_title="x")  # type: ignore[arg-type]
    assert out["ok"] is False
    assert "fact_id" in out["error"]


def test_update_title_nonexistent_fact_id_returns_fail(repo_root):
    """合法 fact_id 但 DB 内不存在 → ok=False, error 描述具体 id。

    与 "非法 fact_id" 区分: 前者是 wrapper 拦截, 后者是 manager 返回 None
    后 wrapper 包成 ok=False。两类错误 LLM 都应能识别。
    """
    out = memory_update_title(fact_id=999_999_999, new_title="x")
    assert out["ok"] is False
    assert "999999999" in out["error"]


@pytest.mark.parametrize(
    "bad_title",
    ["", "   ", "\n\t"],
)
def test_update_title_empty_or_blank_title_returns_fail(bad_title, repo_root):
    """空 / 纯空白 title → ok=False, error 含 "空白" 字样。

    注: ``new_title=None`` 是合法的清空语义, 不在拒绝之列 (见
    ``test_update_title_clears_with_none``)。
    """
    m = MemoryManager()
    f = m.save_fact("note", "x")

    out = memory_update_title(fact_id=f.id, new_title=bad_title)
    assert out["ok"] is False
    assert "空白" in out["error"]


@pytest.mark.parametrize("bad_title", [123, ["a"], {"k": "v"}])
def test_update_title_non_string_title_returns_fail(bad_title, repo_root):
    """非 str / 非 None 的 title → ok=False, error 含 "字符串" 字样。

    None 是合法清空语义, 见 ``test_update_title_clears_with_none``。
    """
    m = MemoryManager()
    f = m.save_fact("note", "x")

    out = memory_update_title(fact_id=f.id, new_title=bad_title)  # type: ignore[arg-type]
    assert out["ok"] is False
    assert "字符串" in out["error"]


def test_update_title_over_max_len_returns_fail(repo_root):
    """title 长度 > 200 → ok=False, error 含 "200" 字样。"""
    m = MemoryManager()
    f = m.save_fact("note", "x")

    out = memory_update_title(fact_id=f.id, new_title="x" * 201)
    assert out["ok"] is False
    assert "200" in out["error"]


def test_update_title_does_not_change_content_or_category(repo_root):
    """更新 title 不应误伤 content / category (整列覆盖语义)。"""
    m = MemoryManager()
    f = m.save_fact("preference", "user likes concise responses")

    out = memory_update_title(fact_id=f.id, new_title="renamed")
    assert out["ok"] is True
    assert out["fact"]["content"] == "user likes concise responses"
    assert out["fact"]["category"] == "preference"


def test_update_title_coerces_string_fact_id(repo_root):
    """LLM 偶尔会把 fact_id 写成字符串 "42"; wrapper 应能正确 coerce。

    与 ``_parse_fact_id`` 单测互补: 这里走 wrapper 全路径。
    """
    m = MemoryManager()
    f = m.save_fact("note", "x", title="old")

    out = memory_update_title(fact_id=str(f.id), new_title="new")
    assert out["ok"] is True
    assert out["id"] == f.id


def test_update_title_json_serializable(repo_root):
    """成功 + 失败两路返回都应能 json.dumps。"""
    m = MemoryManager()
    f = m.save_fact("note", "x", title="old")

    ok = memory_update_title(fact_id=f.id, new_title="new")
    json.dumps(ok)

    fail = memory_update_title(fact_id="not-an-int", new_title="new")
    json.dumps(fail)


# === registry 集成测试 ===
# 确保两个新 wrapper 真的出现在默认 registry 里, 且 schema 包含 required 字段。


def test_recall_by_title_registered_in_default_registry():
    """``memory_recall_by_title`` 应在 ``build_default_registry`` 里。"""
    from xragent.tools.registry import build_default_registry

    r = build_default_registry()
    td = r.get("memory_recall_by_title")
    assert td.handler is memory_tools.memory_recall_by_title
    # title 在 required 里 (LLM 工具调用强约束)
    assert "title" in td.input_schema.get("required", [])


def test_update_title_registered_in_default_registry():
    """memory_update_title 应在 build_default_registry 里, 且 required 含 fact_id + new_title。"""
    from xragent.tools.registry import build_default_registry

    r = build_default_registry()
    td = r.get("memory_update_title")
    assert td.handler is memory_tools.memory_update_title
    required = set(td.input_schema.get("required", []))
    assert "fact_id" in required
    assert "new_title" in required


def test_registry_run_memory_recall_by_title(repo_root):
    """通过 registry.run 调用应与直调 wrapper 等价 (走 HITL gate=None 路径)。"""
    from xragent.tools.registry import build_default_registry

    m = MemoryManager()
    f = m.save_fact("note", "via registry", title="reg-title")

    r = build_default_registry()
    out = r.run("memory_recall_by_title", {"title": "reg-title", "k": 5})
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["facts"][0]["id"] == f.id


def test_registry_run_memory_update_title(repo_root):
    """通过 registry.run 调用 update_title 应落 DB, 再 recall_by_title 命中。"""
    from xragent.tools.registry import build_default_registry

    m = MemoryManager()
    f = m.save_fact("note", "via registry", title="old-reg")

    r = build_default_registry()
    out = r.run(
        "memory_update_title",
        {"fact_id": f.id, "new_title": "new-reg"},
    )
    assert out["ok"] is True
    assert out["new_title"] == "new-reg"

    # 再 recall_by_title 验证落库
    recall = r.run("memory_recall_by_title", {"title": "new-reg", "k": 5})
    assert recall["count"] == 1
    assert recall["facts"][0]["id"] == f.id
