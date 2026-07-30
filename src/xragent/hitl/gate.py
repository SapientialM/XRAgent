"""HITL Gate：审批门。

封装"高危动作需要人类审批"的逻辑。core 推理循环里每次调用高危工具前，
会构造一个 :class:`ApprovalRequest` 交给 :meth:`HitlGate.request`，由
:class:`HitlGate` 根据 ``settings.hitl_default`` 决定：直接放行 / 直接
拒绝 / 转给人工 channel（默认 stdin）。channel 返回 :class:`ApprovalResult`，
可能携带 ``EDIT`` 决策下的 ``edited_args`` —— 调用方据此改写入参再执行。
"""
from __future__ import annotations

import enum
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from ..config.settings import get_settings


# === _stdin_channel 决策语法 ===
#
# 用户在 stdin 上一行输入,首 token 决定决策:
#   * 命中 _APPROVE_INPUTS -> APPROVE
#   * 命中 _REJECT_INPUTS  -> REJECT
#   * 命中 _EDIT_PREFIX    -> EDIT (后续 token 解析为 JSON)
#   * 其它                 -> REJECT, reason="未识别输入"
#
# 空字符串视作"接受默认"——上游 prompt 一般带 [Y/n], 多数用户按回车 = 同意。
# 抽到模块级 frozenset 后,_stdin_channel 体内只剩 ``line in _APPROVE_INPUTS``
# 这种一行判断;且后续若有第二个 channel 想共用同一语法,直接 import 即可。
_APPROVE_INPUTS: frozenset[str] = frozenset({"y", "Y", "yes", "ok", ""})
_REJECT_INPUTS: frozenset[str] = frozenset({"n", "N", "no"})
_EDIT_PREFIX: str = "e:"


class Decision(enum.Enum):
    """HITL 审批的三种可能结果。

    Attributes:
        APPROVE: 放行，沿用原 ``tool_args`` 执行。
        REJECT: 拒绝，调用方应直接返回 blocked envelope。
        EDIT: 改写 + 放行。``ApprovalResult.edited_args`` 携带替换后的
            args；调用方应**保证**它是 dict（handler 后续会做 ``**`` 解包），
            非 dict 由调用方自己兜底成 REJECT，gate 不在这里二次校验。
    """

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit_and_approve"


@dataclass
class ApprovalRequest:
    """一个待审批的高危动作。

    Attributes:
        tool_name: 触发审批的工具名（registry 中的注册名）。
        tool_args: 实际将要传给 handler 的 kwargs；EDIT 决策允许替换它。
            值是 ``Any`` 因为 JSON 形态任意（str / int / list / dict）。
        risk: 风险等级字符串（``"high"`` / ``"medium"`` …），仅用于展示，
            是否真的"高危"由 channel 自行判定，gate 不替它把关。
        summary: 一行人类可读摘要，便于审批人快速理解要做什么。
        tool_call_id: 可选的外部 trace id（多 agent 并发时用于对账）；
            默认空串。
    """

    tool_name: str
    tool_args: dict[str, Any]
    risk: str
    summary: str
    tool_call_id: str = ""

    def render(self) -> str:
        """把请求序列化成给人类看的 prompt 文本（写到 stderr）。

        末尾留出 ``决策 [y/n/e:<json>]: `` 提示，让 stdin channel 能直接
        ``input()`` 读取一行；不含末尾换行，方便 prompt 紧贴用户输入。
        """
        return (
            f"[HITL] 高危动作请求审批\n"
            f"  工具: {self.tool_name} (risk={self.risk})\n"
            f"  摘要: {self.summary}\n"
            f"  参数: {self.tool_args}\n"
            f"  决策 [y/n/e:<json>]: "
        )


@dataclass
class ApprovalResult:
    """channel 对一次审批请求的最终答复。

    Attributes:
        decision: 见 :class:`Decision`。
        edited_args: 仅在 ``decision == EDIT`` 时有意义，调用方应用它替换
            ``ApprovalRequest.tool_args`` 后再交给 handler。其它情况下
            应为 ``None``，默认值 ``None``。
        reason: 人类可读理由；REJECT 时必备，方便上层写入审计日志；
            APPROVE / EDIT 时可空，默认 ``""``。
    """

    decision: Decision
    edited_args: dict[str, Any] | None = None
    reason: str = ""


# 一个 channel 就是"接 req → 回 res"的 callable；测试里会注入 fake channel。
Channel = Callable[[ApprovalRequest], ApprovalResult]


class HitlGate:
    """HITL 决策中枢：默认策略 + 可注入的人工 channel。

    ``settings.hitl_default`` 取值约定：
      * ``"approve-all"`` —— 直接放行，reason 标 ``"approve-all"``，
        channel 完全不调用（适合批处理 / CI）。
      * ``"reject-all"`` —— 直接拒绝，reason 标 ``"reject-all"``，
        channel 完全不调用（适合 sandbox / 首次冷启动）。
      * 其它（默认 ``"ask"``）—— 交给 ``self._channel`` 决策。

    channel 在 :meth:`__init__` 注入；运行期可调 :meth:`set_channel` 换掉，
    便于 supervisor 切换 mode（比如从"ask"切到"approve-all"做批量迁移）。
    """

    def __init__(self, channel: Channel | None = None) -> None:
        """构造一个 gate；``channel=None`` 时退化为内置 stdin channel。

        读取 ``settings.hitl_default`` 作为默认策略，并把 channel 锁定为
        ``channel or self._stdin_channel`` —— 后者是个 bound method，
        不需要在外面手绑 self。

        Args:
            channel: 可选的人工 channel；为 None 时用 stdin channel。
        """
        s = get_settings()
        self.default = s.hitl_default
        self._channel = channel or self._stdin_channel

    def request(self, req: ApprovalRequest) -> ApprovalResult:
        """对一条审批请求做决策：默认策略优先，剩下走 channel。

        Args:
            req: 待审批动作。

        Returns:
            :class:`ApprovalResult`。``approve-all`` / ``reject-all`` 时
            不调 channel；其它情况透传 channel 的返回值。
        """
        if self.default == "approve-all":
            return ApprovalResult(Decision.APPROVE, reason="approve-all")
        if self.default == "reject-all":
            return ApprovalResult(Decision.REJECT, reason="reject-all")
        return self._channel(req)

    def _stdin_channel(self, req: ApprovalRequest) -> ApprovalResult:
        """内置 channel：往 stderr 写 prompt，从 stdin 读一行解析。

        解析规则（见模块顶 ``_APPROVE_INPUTS`` / ``_REJECT_INPUTS`` /
        ``_EDIT_PREFIX``）:
          * 命中 ``_APPROVE_INPUTS``（``y`` / ``Y`` / ``yes`` / ``ok`` / 空行）
            → APPROVE（空行视作"接受默认"，上游 prompt 一般带 ``[Y/n]``）。
          * 命中 ``_REJECT_INPUTS``（``n`` / ``N`` / ``no``）→ REJECT（reason 留空）。
          * 命中 ``_EDIT_PREFIX``（``e:<json>``）→ EDIT，``edited_args`` 是
            解析后的对象；JSON 解析失败 → REJECT，reason 携带错误细节。
          * 其它输入 → REJECT，reason="未识别输入"。

        ``EOFError``（stdin 被关了，例如 CI 里没 tty）→ REJECT，
        reason="stdin EOF"——宁可保守拒绝也别擅自放行。
        """
        sys.stderr.write(req.render())
        sys.stderr.flush()
        try:
            line = input()
        except EOFError:
            return ApprovalResult(Decision.REJECT, reason="stdin EOF")
        line = line.strip()
        if line in _APPROVE_INPUTS:
            return ApprovalResult(Decision.APPROVE)
        if line in _REJECT_INPUTS:
            return ApprovalResult(Decision.REJECT)
        if line.startswith(_EDIT_PREFIX):
            try:
                edited = json.loads(line[len(_EDIT_PREFIX):].strip())
                return ApprovalResult(Decision.EDIT, edited_args=edited)
            except json.JSONDecodeError as e:
                return ApprovalResult(Decision.REJECT, reason=f"edit 解析失败: {e}")
        return ApprovalResult(Decision.REJECT, reason="未识别输入")

    def set_channel(self, channel: Channel) -> None:
        """运行期替换人工 channel（例如切到 webhook / silent mode）。

        注意：本方法**不**校验 ``channel`` 是否真的可调用——故意不引入契约
        检查，让测试可以注入 ``lambda req: ApprovalResult(Decision.APPROVE)``
        这种极简 fake。生产环境要靠调用方自觉。
        """
        self._channel = channel