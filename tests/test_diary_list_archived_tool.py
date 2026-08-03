"""``tools.diary_tools.diary_list_archived`` 薄包装 + 注册表契约。

``util/diary_archive.list_archived_weeks`` 核心行为已在
``tests/test_diary_archive.py::test_list_archived_weeks_*`` 覆盖 (纯函数
层)；本文件只锁 LLM 工具层 wrapper + registry 注册 — 五件事:

  1. wrapper 路径源唯一 (``settings.diary_dir``), 不接受外部参数 — 与
     ``diary_archive`` / ``diary_write`` 同一真相源, 防止路径漂移。
  2. 返回 envelope ``{"ok": True, "weeks": [(iso_year, iso_week), ...]}``
     — LLM 工具层契约 (always returns dict, ok 字段必备)。
  3. OSError 兜底 — 底层 ``list_archived_weeks`` 抛异常时返回 ``ok=False``,
     错误信息含 ``"列出已归档周失败:"`` 前缀便于上层 grep。
  4. ``build_default_registry()`` 必须把 ``diary_list_archived`` 登记进去 —
     spec.name / risk / handler / schema 全部对得上。
  5. 通过 ``ToolRegistry.run("diary_list_archived", {}, gate=None)`` 端到端
     跑通 — happy path 返回 ``weeks`` 列表 (空或非空均可), 不抛异常。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xragent.config.settings import get_settings
from xragent.tools import diary_tools
from xragent.tools.registry import build_default_registry


# ---------------------------------------------------------------------------
# wrapper 契约 (纯函数层)
# ---------------------------------------------------------------------------


def test_diary_list_archived_uses_settings_diary_dir(repo_root, monkeypatch):
    """spy ``list_archived_weeks``, 验证 wrapper 传的就是 ``settings.diary_dir``。"""
    calls: list[tuple] = []

    def spy(diary_dir):
        calls.append(diary_dir)
        return [(2026, 30)]

    monkeypatch.setattr(diary_tools, "list_archived_weeks", spy)

    r = diary_tools.diary_list_archived()

    assert r["ok"] is True
    assert r["weeks"] == [(2026, 30)]
    assert len(calls) == 1, f"应调一次 list_archived_weeks, 实际 {len(calls)} 次"
    assert Path(calls[0]) == get_settings().diary_dir


def test_diary_list_archived_empty_returns_ok_true_with_empty_list(repo_root, monkeypatch):
    """``archive/`` 不存在 / 为空时, 仍应返回 ``ok=True`` + ``weeks=[]``, 不是错误。"""
    monkeypatch.setattr(
        diary_tools, "list_archived_weeks", lambda diary_dir: []
    )

    r = diary_tools.diary_list_archived()

    assert r == {"ok": True, "weeks": []}


def test_diary_list_archived_oserror_returns_ok_false(repo_root, monkeypatch):
    """底层 OSError (磁盘满 / 权限) 应被 wrapper 兜底成 ``ok=False``。"""
    def boom(diary_dir):
        raise PermissionError(f"denied: {diary_dir}")

    monkeypatch.setattr(diary_tools, "list_archived_weeks", boom)

    r = diary_tools.diary_list_archived()

    assert r["ok"] is False
    assert "error" in r
    # 错误前缀稳定, 方便上层 grep + 排障
    assert "列出已归档周失败" in r["error"]
    assert "PermissionError" in r["error"]


def test_diary_list_archived_does_not_accept_path_argument():
    """wrapper 不应接受 ``diary_dir`` 参数 — 路径源唯一, 跟 ``diary_archive`` 对齐。

    如果哪天有人加了 ``diary_dir=...`` 参数, 这个测试会立刻红掉, 提醒
    review 把这条单真相源原则再 review 一遍。
    """
    import inspect

    sig = inspect.signature(diary_tools.diary_list_archived)
    assert list(sig.parameters) == [], (
        f"diary_list_archived 不应有任何参数, 实际: {list(sig.parameters)}"
    )


# ---------------------------------------------------------------------------
# 注册表契约 (registry 层)
# ---------------------------------------------------------------------------


def test_build_default_registry_includes_diary_list_archived():
    """``build_default_registry()`` 必须把 ``diary_list_archived`` 登记进去。"""
    r = build_default_registry()
    assert "diary_list_archived" in r.names()


def test_diary_list_archived_spec_fields_are_correct():
    """ToolDef 的 name / risk / handler / schema 都对得上。"""
    r = build_default_registry()
    specs = {s.name: s for s in r.specs()}
    assert "diary_list_archived" in specs

    spec = specs["diary_list_archived"]
    assert spec.name == "diary_list_archived"
    # 纯函数 + 只读本地 archive/ 目录, 视为 low risk
    assert spec.risk == "low"
    # 描述里要带"ISO 周"或"已归档"关键字, LLM 才能理解用途
    desc = spec.description
    assert "ISO 周" in desc or "已归档" in desc or "archive" in desc


def test_diary_list_archived_schema_is_well_formed_json_schema():
    """JSON Schema: 空 properties, 无 required (无参工具)。"""
    r = build_default_registry()
    spec = r.specs()[r.names().index("diary_list_archived")]
    schema = spec.input_schema

    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert schema.get("properties") == {}
    # 无 required 字段 (无参工具) — 不强制写 [] 也行, 但不能有非空
    assert not schema.get("required"), (
        f"diary_list_archived 不应有任何 required 字段, 实际: {schema.get('required')}"
    )


def test_registry_run_diary_list_archived_end_to_end(repo_root, monkeypatch):
    """端到端: 通过 ToolRegistry.run 调通, 返回 envelope 形态正确。"""
    # stub 掉 list_archived_weeks, 避免被真实 fs 状态污染
    monkeypatch.setattr(
        diary_tools, "list_archived_weeks", lambda diary_dir: [(2026, 28), (2026, 30)]
    )

    r = build_default_registry()
    result = r.run("diary_list_archived", {}, gate=None)

    assert result["ok"] is True
    assert result["weeks"] == [(2026, 28), (2026, 30)]


def test_registry_handler_identity_matches_module_attr():
    """registry 内部存储的 handler 必须 identity 等于模块顶层函数。

    ToolSpec 不携带 handler (它只描述 schema 给 LLM), 但 ``ToolRegistry._tools``
    里的 ToolDef 有 handler — 走 ``r._tools[name].handler`` 拿到同一个函数,
    验证 identity。
    """
    r = build_default_registry()
    assert "diary_list_archived" in r._tools
    handler = r._tools["diary_list_archived"].handler
    assert handler is diary_tools.diary_list_archived