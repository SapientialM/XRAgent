"""ToolRegistry + build_default_registry：之前零覆盖，补齐边界条件。

重点覆盖：
  * register 重复 → ValueError；unregister 缺失 name → 静默（dict.pop 语义）
  * get 缺失 name → KeyError（不是 IndexError）
  * names / specs 反映当前注册集合，且 specs 字段映射正确（含 risk）
  * run：
      - low risk：gate 不被调用，也不注入 hitl_approved
      - high risk + gate=None：跳过审批，直接执行
      - high risk + APPROVE / REJECT / EDIT 三种决策分支
      - handler 抛异常 → ok=False 且 error 含异常类型名（不向上抛）
      - 未注册 name → KeyError 向上抛（不静默吞）
  * build_default_registry：
      - 默认 evolution_enabled=True 时含 propose_self_replace / terminate
      - evolution_enabled=False 时这两个名字被 unregister
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from xragent.config import settings as settings_mod
from xragent.core.backend import ToolSpec
from xragent.hitl.gate import ApprovalRequest, ApprovalResult, Decision
from xragent.tools.registry import ToolDef, ToolRegistry, build_default_registry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class _CallLog:
    """记录 hitl 决策与 handler 调用的最小载体。"""
    gate_calls: list[ApprovalRequest]
    handler_calls: list[dict]


def _ok(**kwargs):
    return {"ok": True, **kwargs}


def _boom(**kwargs):
    raise RuntimeError("boom inside handler")


def _make_registry_with(tool: ToolDef) -> ToolRegistry:
    r = ToolRegistry()
    r.register(tool)
    return r


def _gate(returning: ApprovalResult):
    """返回一个会记录调用并产出固定 ApprovalResult 的 gate。"""
    log = _CallLog(gate_calls=[], handler_calls=[])

    def _g(req: ApprovalRequest) -> ApprovalResult:
        log.gate_calls.append(req)
        return returning

    return _g, log


# ---------------------------------------------------------------------------
# ToolDef dataclass
# ---------------------------------------------------------------------------


def test_tool_def_fields_are_stored():
    def h(**_):
        return {}

    td = ToolDef(
        name="t",
        description="d",
        input_schema={"type": "object"},
        risk="low",
        handler=h,
    )
    assert td.name == "t"
    assert td.description == "d"
    assert td.input_schema == {"type": "object"}
    assert td.risk == "low"
    assert td.handler is h


def test_tool_def_default_risk_is_low_via_explicit_construction():
    """ToolDef 没有 risk 默认值；调用方必须显式指定。这里锁死风险字符串集合。"""
    allowed = {"low", "high", "medium"}
    r = ToolRegistry()

    for risk in allowed:
        td = ToolDef(name=f"t-{risk}", description="", input_schema={}, risk=risk, handler=lambda **_: {})
        r.register(td)
        assert r.get(f"t-{risk}").risk == risk


# ---------------------------------------------------------------------------
# register / unregister / get
# ---------------------------------------------------------------------------


def test_register_duplicate_raises_valueerror():
    r = ToolRegistry()
    r.register(ToolDef(name="dup", description="", input_schema={}, risk="low", handler=lambda **_: {}))
    with pytest.raises(ValueError) as ei:
        r.register(ToolDef(name="dup", description="x", input_schema={}, risk="low", handler=lambda **_: {}))
    assert "重复注册" in str(ei.value)
    assert "dup" in str(ei.value)


def test_unregister_existing_name_removes_it():
    r = ToolRegistry()
    r.register(ToolDef(name="x", description="", input_schema={}, risk="low", handler=lambda **_: {}))
    r.unregister("x")
    assert "x" not in r.names()
    with pytest.raises(KeyError):
        r.get("x")


def test_unregister_missing_name_is_silent():
    """unregister 未注册的 name 应静默 noop（dict.pop default None 语义），不抛。"""
    r = ToolRegistry()
    # 没有任何副作用前先记录 baseline
    assert r.names() == []
    r.unregister("never-existed")  # 必须不抛
    assert r.names() == []


def test_get_unknown_raises_keyerror():
    r = ToolRegistry()
    with pytest.raises(KeyError) as ei:
        r.get("nope")
    assert "未知工具" in str(ei.value)
    assert "nope" in str(ei.value)


def test_get_returns_same_object_that_was_registered():
    td = ToolDef(name="same", description="", input_schema={}, risk="low", handler=lambda **_: {})
    r = ToolRegistry()
    r.register(td)
    assert r.get("same") is td


# ---------------------------------------------------------------------------
# names / specs
# ---------------------------------------------------------------------------


def test_names_empty_registry():
    assert ToolRegistry().names() == []


def test_names_preserve_insertion_order():
    r = ToolRegistry()
    for n in ("c", "a", "b"):
        r.register(ToolDef(name=n, description="", input_schema={}, risk="low", handler=lambda **_: {}))
    assert r.names() == ["c", "a", "b"]


def test_specs_empty_registry_returns_empty_list():
    assert ToolRegistry().specs() == []


def test_specs_maps_all_fields_including_risk():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    r = ToolRegistry()
    r.register(ToolDef(name="t", description="desc", input_schema=schema, risk="high", handler=lambda **_: {}))
    specs = r.specs()
    assert len(specs) == 1
    s = specs[0]
    assert isinstance(s, ToolSpec)
    assert s.name == "t"
    assert s.description == "desc"
    assert s.input_schema == schema
    assert s.risk == "high"


def test_specs_reflects_unregister():
    r = ToolRegistry()
    r.register(ToolDef(name="a", description="", input_schema={}, risk="low", handler=lambda **_: {}))
    r.register(ToolDef(name="b", description="", input_schema={}, risk="high", handler=lambda **_: {}))
    assert {s.name for s in r.specs()} == {"a", "b"}
    r.unregister("a")
    assert [s.name for s in r.specs()] == ["b"]


# ---------------------------------------------------------------------------
# run：low risk 直通
# ---------------------------------------------------------------------------


def test_run_low_risk_calls_handler_without_gate():
    handler_called = {"n": 0}

    def h(x: int = 0) -> dict:
        handler_called["n"] += 1
        return {"ok": True, "x": x}

    r = _make_registry_with(ToolDef(name="echo", description="", input_schema={}, risk="low", handler=h))

    # 即便传了 gate，low risk 也不应触发审批
    gate, log = _gate(ApprovalResult(Decision.APPROVE))
    out = r.run("echo", {"x": 7}, gate=gate)
    assert out == {"ok": True, "x": 7}
    assert handler_called["n"] == 1
    assert log.gate_calls == []  # gate 一次都没被问
    assert "hitl_approved" not in out


# ---------------------------------------------------------------------------
# run：high risk 跳过审批（gate is None）
# ---------------------------------------------------------------------------


def test_run_high_risk_with_no_gate_skips_approval():
    """高危工具但 gate=None 时直接执行：不加 hitl_approved。"""
    handler_called = {"n": 0}

    def h(**_):
        handler_called["n"] += 1
        return {"ok": True}

    r = _make_registry_with(ToolDef(name="hot", description="", input_schema={}, risk="high", handler=h))
    out = r.run("hot", {}, gate=None)
    assert out == {"ok": True}
    assert handler_called["n"] == 1
    assert "hitl_approved" not in out


# ---------------------------------------------------------------------------
# run：high risk 三态决策
# ---------------------------------------------------------------------------


def test_run_high_risk_approve_injects_hitl_approved():
    def h(**kwargs):
        # 关键：handler 必须用 EDIT 改过的 args，否则测试不严谨
        return {"ok": True, "echoed": kwargs}

    r = _make_registry_with(ToolDef(name="hot", description="", input_schema={}, risk="high", handler=h))
    gate, log = _gate(ApprovalResult(Decision.APPROVE, reason="ok"))

    out = r.run("hot", {"v": 1}, gate=gate)
    assert out["ok"] is True
    assert out["hitl_approved"] is True
    assert out["echoed"] == {"v": 1}
    assert len(log.gate_calls) == 1
    assert log.gate_calls[0].tool_name == "hot"
    assert log.gate_calls[0].tool_args == {"v": 1}
    assert log.gate_calls[0].risk == "high"


def test_run_high_risk_reject_short_circuits_without_calling_handler():
    handler_called = {"n": 0}

    def h(**_):
        handler_called["n"] += 1
        return {"ok": True}

    r = _make_registry_with(ToolDef(name="hot", description="", input_schema={}, risk="high", handler=h))
    gate, log = _gate(ApprovalResult(Decision.REJECT, reason="nope"))

    out = r.run("hot", {"v": 1}, gate=gate)
    assert out["ok"] is False
    assert out["blocked_by"] == "hitl"
    assert out["reason"] == "nope"
    assert handler_called["n"] == 0  # handler 没被执行
    assert "hitl_approved" not in out


def test_run_high_risk_edit_replaces_args_and_still_runs():
    """EDIT 决策：handler 收到的应是 edited_args，而非原始 args。"""
    handler_received: dict = {}

    def h(**kwargs):
        handler_received.update(kwargs)
        return {"ok": True}

    r = _make_registry_with(ToolDef(name="hot", description="", input_schema={}, risk="high", handler=h))
    edited = {"v": 999, "extra": "added"}
    gate, log = _gate(ApprovalResult(Decision.EDIT, edited_args=edited, reason="massage"))

    out = r.run("hot", {"v": 1, "leak": "secret"}, gate=gate)
    assert handler_received == edited       # 原 args 被替换
    assert "leak" not in handler_received   # 原 args 不会泄露进来
    assert out["ok"] is True
    assert out["hitl_approved"] is True


def test_run_high_risk_edit_with_none_edited_args_falls_back_to_original():
    """EDIT 但 edited_args=None 时（接口契约允许），应回退到原 args。"""
    seen: dict = {}

    def h(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    r = _make_registry_with(ToolDef(name="hot", description="", input_schema={}, risk="high", handler=h))
    gate, _ = _gate(ApprovalResult(Decision.EDIT, edited_args=None))

    out = r.run("hot", {"a": 1}, gate=gate)
    assert seen == {"a": 1}
    assert out["hitl_approved"] is True


# ---------------------------------------------------------------------------
# run：handler 异常 + 未注册
# ---------------------------------------------------------------------------


def test_run_handler_exception_is_swallowed_with_error_envelope():
    r = _make_registry_with(ToolDef(name="boom", description="", input_schema={}, risk="low", handler=_boom))
    out = r.run("boom", {})
    assert out["ok"] is False
    # 错误信息应含异常类型名，方便上层定位
    assert "RuntimeError" in out["error"]
    assert "boom inside handler" in out["error"]


def test_run_high_risk_handler_exception_after_approve_is_swallowed():
    """高危 + APPROVE 后 handler 仍可能抛 → 应被吞并打 ok=False，但 hitl_approved 标记保留。"""
    r = _make_registry_with(ToolDef(name="hot-boom", description="", input_schema={}, risk="high", handler=_boom))
    gate, _ = _gate(ApprovalResult(Decision.APPROVE))
    out = r.run("hot-boom", {}, gate=gate)
    assert out["ok"] is False
    assert "RuntimeError" in out["error"]
    assert out["hitl_approved"] is True


def test_run_unknown_tool_propagates_keyerror():
    """未注册的 name → KeyError 向上抛（不像 handler 异常那样被吞），便于上层早失败。"""
    r = ToolRegistry()
    with pytest.raises(KeyError):
        r.run("nope", {})


# ---------------------------------------------------------------------------
# build_default_registry
# ---------------------------------------------------------------------------


def _core_names(r: ToolRegistry) -> set[str]:
    return set(r.names())


def test_build_default_registry_includes_core_tools_when_evolution_enabled(repo_root):
    """conftest 默认把 XRAGENT_EVOLUTION_ENABLED 设成 'true'。"""
    s = settings_mod.get_settings()
    # 显式断言，确保测试假设成立
    assert s.evolution_enabled is True

    r = build_default_registry()
    names = _core_names(r)
    # 必须有的核心工具
    for must in ("read_file", "write_file", "run_cmd", "git_commit", "git_push",
                 "list_dir", "memory_save", "diary_write"):
        assert must in names, f"缺核心工具: {must}"

    # evolution 开时，必须有蜕皮/终止
    assert "propose_self_replace" in names
    assert "terminate" in names


def test_build_default_registry_drops_evolution_tools_when_disabled(repo_root, monkeypatch):
    """evolution_enabled=False 时，propose_self_replace 和 terminate 应被 unregister。"""
    s = settings_mod.get_settings()
    monkeypatch.setattr(s, "evolution_enabled", False)

    r = build_default_registry()
    names = _core_names(r)
    # 其它核心仍应有
    assert "read_file" in names
    assert "run_cmd" in names
    assert "diary_write" in names
    # 蜕皮/终止被摘掉
    assert "propose_self_replace" not in names
    assert "terminate" not in names


def test_build_default_registry_specs_risk_matches_tool_kind():
    """从 build_default_registry 的 specs 看：read_file/list_dir/memory_save/diary_write 应是 low；write_file/run_cmd/git_commit/git_push/propose_self_replace/terminate 应是 high。"""
    r = build_default_registry()
    by_name = {s.name: s for s in r.specs()}

    low_risk = ("read_file", "list_dir", "memory_save", "diary_write")
    high_risk = ("write_file", "run_cmd", "git_commit", "git_push",
                 "propose_self_replace", "terminate")

    for n in low_risk:
        assert n in by_name, f"缺工具: {n}"
        assert by_name[n].risk == "low", f"{n} 风险等级应为 low，实际 {by_name[n].risk}"
    for n in high_risk:
        assert n in by_name, f"缺工具: {n}"
        assert by_name[n].risk == "high", f"{n} 风险等级应为 high，实际 {by_name[n].risk}"
