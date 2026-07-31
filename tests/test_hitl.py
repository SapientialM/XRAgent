"""HITL Gate 三态决策。"""
from __future__ import annotations

import pytest

from xragent.hitl.gate import (
    ApprovalRequest,
    ApprovalResult,
    Decision,
    HitlGate,
    _parse_stdin_line,
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
    # 默认策略 reason 必须沿用 key 字符串,方便审计日志一眼可读
    assert r.reason == "approve-all"


def test_reject_all_default(monkeypatch):
    monkeypatch.setenv("XRAGENT_HITL_DEFAULT", "reject-all")
    from xragent.config import settings as sm
    sm.reset_settings_cache()
    gate = HitlGate()
    r = gate.request(ApprovalRequest("write_file", {"path": "x"}, "high", "test"))
    assert r.decision == Decision.REJECT
    assert r.reason == "reject-all"


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


def test_unknown_default_falls_through_to_channel():
    """非 ``approve-all`` / ``reject-all`` 的值（含 ``"interactive"`` /
    ``"ask"`` / 拼错字符串）必须走 channel,而非被错误识别成默认策略。"""
    seen: list[ApprovalRequest] = []

    def spy_channel(req: ApprovalRequest) -> ApprovalResult:
        seen.append(req)
        return ApprovalResult(Decision.APPROVE, reason="spy")

    gate = HitlGate(channel=spy_channel)
    r = gate.request(ApprovalRequest("write_file", {"path": "x"}, "high", "test"))
    assert r.decision == Decision.APPROVE
    assert r.reason == "spy"  # 不是 "ask" / "interactive" —— 那些是 key,不是 reason
    assert len(seen) == 1


# === _parse_stdin_line: pure-function 分支覆盖 ===
#
# 抽 helper 最大的收益就是这一组用例: 不用伪造 stdin / stderr,
# 直接调函数就能把每个分支跑一遍,包括大小写 / 空白 / JSON 错误 / 未知输入。

@pytest.mark.parametrize("line", ["y", "Y", "yes", "ok", "", "  y  ", "\n"])
def test_parse_stdin_line_approve(line):
    r = _parse_stdin_line(line)
    assert r.decision == Decision.APPROVE
    assert r.edited_args is None
    assert r.reason == ""


@pytest.mark.parametrize("line", ["n", "N", "no", "  n  "])
def test_parse_stdin_line_reject(line):
    r = _parse_stdin_line(line)
    assert r.decision == Decision.REJECT
    assert r.edited_args is None
    # REJECT 来自 _REJECT_INPUTS 时 reason 留空,与原契约一致
    assert r.reason == ""


def test_parse_stdin_line_edit_valid_json():
    r = _parse_stdin_line('e:{"path": "/tmp/x", "content": "hi"}')
    assert r.decision == Decision.EDIT
    assert r.edited_args == {"path": "/tmp/x", "content": "hi"}
    assert r.reason == ""


def test_parse_stdin_line_edit_with_padding():
    """e: 后允许空白,只要 JSON 本身合法。"""
    r = _parse_stdin_line("e:   {\"k\": 1}  ")
    assert r.decision == Decision.EDIT
    assert r.edited_args == {"k": 1}


def test_parse_stdin_line_edit_invalid_json_rejects():
    r = _parse_stdin_line("e:{not valid}")
    assert r.decision == Decision.REJECT
    assert r.edited_args is None
    # reason 必须带上原始错误细节,方便用户改
    assert "edit 解析失败" in r.reason


@pytest.mark.parametrize("line", ["maybe", "yyy", "e", "edit", ":"])
def test_parse_stdin_line_unrecognized_rejects(line):
    r = _parse_stdin_line(line)
    assert r.decision == Decision.REJECT
    assert r.edited_args is None
    assert r.reason == "未识别输入"