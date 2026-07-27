"""HITL Gate 三态决策。"""
from __future__ import annotations

from xragent.hitl.gate import (
    ApprovalRequest,
    ApprovalResult,
    Decision,
    HitlGate,
)


def test_approve_all_default():
    gate = HitlGate()
    gate.default = "approve-all"
    r = gate.request(ApprovalRequest("write_file", {"path": "x"}, "high", "test"))
    assert r.decision == Decision.APPROVE


def test_reject_all_default():
    gate = HitlGate()
    gate.default = "reject-all"
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
