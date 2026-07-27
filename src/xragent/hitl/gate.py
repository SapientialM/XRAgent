"""HITL Gate：审批门。"""
from __future__ import annotations

import enum
import sys
from dataclasses import dataclass
from typing import Callable

from ..config.settings import get_settings


class Decision(enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit_and_approve"


@dataclass
class ApprovalRequest:
    tool_name: str
    tool_args: dict
    risk: str
    summary: str
    tool_call_id: str = ""

    def render(self) -> str:
        return (
            f"[HITL] 高危动作请求审批\n"
            f"  工具: {self.tool_name} (risk={self.risk})\n"
            f"  摘要: {self.summary}\n"
            f"  参数: {self.tool_args}\n"
            f"  决策 [y/n/e:<json>]: "
        )


@dataclass
class ApprovalResult:
    decision: Decision
    edited_args: dict | None = None
    reason: str = ""


class HitlGate:
    def __init__(self, channel: Callable[[ApprovalRequest], ApprovalResult] | None = None):
        s = get_settings()
        self.default = s.hitl_default
        self._channel = channel or self._stdin_channel

    def request(self, req: ApprovalRequest) -> ApprovalResult:
        if self.default == "approve-all":
            return ApprovalResult(Decision.APPROVE, reason="approve-all")
        if self.default == "reject-all":
            return ApprovalResult(Decision.REJECT, reason="reject-all")
        return self._channel(req)

    def _stdin_channel(self, req: ApprovalRequest) -> ApprovalResult:
        sys.stderr.write(req.render())
        sys.stderr.flush()
        try:
            line = input()
        except EOFError:
            return ApprovalResult(Decision.REJECT, reason="stdin EOF")
        line = line.strip()
        if line in ("y", "Y", "yes", "ok", ""):
            return ApprovalResult(Decision.APPROVE)
        if line in ("n", "N", "no"):
            return ApprovalResult(Decision.REJECT)
        if line.startswith("e:"):
            import json
            try:
                edited = json.loads(line[2:].strip())
                return ApprovalResult(Decision.EDIT, edited_args=edited)
            except json.JSONDecodeError as e:
                return ApprovalResult(Decision.REJECT, reason=f"edit 解析失败: {e}")
        return ApprovalResult(Decision.REJECT, reason="未识别输入")

    def set_channel(self, channel: Callable[[ApprovalRequest], ApprovalResult]) -> None:
        self._channel = channel
