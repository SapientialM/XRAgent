"""HITL Gate 三态决策。"""
from __future__ import annotations

import pytest

from xragent.hitl.gate import (
    ApprovalRequest,
    ApprovalResult,
    Decision,
    HitlGate,
)


@pytest.fixture(autouse=True)
def _force_interactive(monkeypatch):
    """所有 HITL 测试都跑在 interactive 模式（避开 .env 的 approve-all）。"""
    monkeypatch.setenv("XRAGENT_HITL_DEFAULT", "interactive")
    from xragent.config import settings as sm
    sm.reset_settings_cache()
    yield


def test_approve_all_default(monkeypatch):
    monkeypatch.setenv("XRAGENT_HITL_DEFAULT", "approve-all")
    from xragent.config import settings as sm
    sm.reset_settings_cache()
    gate = HitlGate()
    r = gate.request(ApprovalRequest("write_file", {"path": "x"}, "high", "test"))
    assert r.decision == Decision.APPROVE


def test_reject_all_default(monkeypatch):
    monkeypatch.setenv("XRAGENT_HITL_DEFAULT", "reject-all")
    from xragent.config import settings as sm
    sm.reset_settings_cache()
    gate = HitlGate()
    r = gate.request(ApprovalRequest("write_file", {"path": "x"}, "high", "test"))
    assert r.decision == Decision.REJECT


def test_custom_channel_override():
    seen: list[ApprovalRequest] = []

    def custom_channel(req: ApprovalRequest) -> ApprovalResult:
        seen.append(req)
        return ApprovalResult(Decision.APPROVE, reason="custom")

    gate = HitlGate(channel=custom_channel)
    r = gate.request(ApprovalRequest("run_cmd", {"cmd": "ls"}, "high", "test"))
    assert r.decision == Decision.APPROVE
    assert r.reason == "custom"
    assert len(seen) == 1
    assert seen[0].tool_name == "run_cmd"


def test_request_renders_summary():
    req = ApprovalRequest("write_file", {"path": "x", "content": "y"}, "high", "create x.py")
    out = req.render()
    assert "write_file" in out
    assert "create x.py" in out
