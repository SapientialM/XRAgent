"""ReAct 主循环。"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from ..config.settings import get_settings
from ..core.backend import BackendProtocol, Message, ToolCall
from ..core.dream import assemble_system_prompt
from ..core.turn import TraceRecorder, TurnRecord, new_turn_id
from ..hitl.gate import HitlGate
from ..memory.manager import MemoryManager
from ..snapshot.side_git import SideGit, Snapshot
from ..tools.registry import ToolRegistry, build_default_registry


# user_text 在 snapshot note 里的截断长度,沿用原 magic number;集中到模块顶层常量
# 便于日后统一调整(若 turn_id 长度策略变更,只需改一处)。
_USER_TEXT_NOTE_MAX = 40


def make_tool_message(tool_call_id: str, content: Any) -> Message:
    """把工具执行结果包装成 LangChain 风格的 ``role="tool"`` 消息。

    用 ``json.dumps(..., ensure_ascii=False)`` 序列化结果,让非 ASCII
    字段 (中文路径、错误堆栈) 在 LLM 端不变成 ``\\uXXXX`` 转义;
    ``tool_call_id`` 必须与上一轮 assistant ``tool_calls`` 的 id 对齐,
    否则多轮 tool 链会断。

    Args:
        tool_call_id: 对应 assistant turn 中 ToolCall 的 ``id`` 字段。
        content: 工具返回的任意可序列化对象 (dict / list / str / 异常文本)。

    Returns:
        Message: ``role="tool"``, ``content`` 为 JSON 字符串的新消息。
    """
    return Message(
        role="tool",
        content=json.dumps(content, ensure_ascii=False),
        tool_call_id=tool_call_id,
    )


def make_assistant_message(turn: Any) -> Message:
    """把 backend 返回的 ``Turn`` 包装成 ``role="assistant"`` 消息。

    ``turn.content`` 为 ``None`` 时降级为空串 (下游消息历史不接受 ``None``);
    ``turn.tool_calls`` 为空时显式置 ``None`` 而非 ``[]``,与上游
    ``BackendProtocol`` 行为对齐,避免 LangChain 端把它当成"有一次空调用"。

    Args:
        turn: :class:`~xragent.core.backend.Turn` 实例 (duck-typed 接收
            ``Any``,避免与 backend 模块的导入顺序耦合)。

    Returns:
        Message: ``role="assistant"``, 可选携带 ``tool_calls`` 的新消息。
    """
    return Message(
        role="assistant",
        content=turn.content or "",
        tool_calls=turn.tool_calls or None,
    )


def _format_turn_diary_body(
    user_text: str,
    final_content: str,
    actions: list[dict],
    wall_ms: int,
    tokens_in: int,
    tokens_out: int,
    error: str | None,
) -> str:
    """拼装单 turn 的人类可读 diary body。

    把"输入 / 回答 / 动作 / 耗时 / 错误"五段定长截断后用 ``\\n\\n`` 拼起来;
    错误段只在 ``error`` 非空时追加,避免空标题。

    Args:
        user_text: 本轮用户原始输入。
        final_content: 最终回答内容 (可能为空)。
        actions: 本轮触发的工具调用列表 (dict 形如
            ``{"step": int, "tool": str, "args": dict, "id": str}``)。
        wall_ms: 本轮总耗时,毫秒。
        tokens_in / tokens_out: 累计 prompt / completion token 数。
        error: 本轮错误信息, ``None`` 时不写错误段。

    Returns:
        str: 多行 markdown 字符串,以单个 ``\\n`` 结尾。
    """
    lines = [
        f"**输入**: {user_text[:200]}",
        f"**回答**: {final_content[:400]}",
        f"**动作**: {[a['tool'] for a in actions]}",
        f"**耗时**: {wall_ms}ms · tokens_in={tokens_in} tokens_out={tokens_out}",
    ]
    if error:
        lines.append(f"**错误**: {error}")
    return "\n\n".join(lines) + "\n"


def _record_turn_diary(
    turn_id: str,
    user_text: str,
    final_content: str,
    actions: list[dict],
    wall_ms: int,
    tokens_in: int,
    tokens_out: int,
    error: str | None,
) -> None:
    """把 turn 摘要追加到 ``diary/YYYY-MM-DD.md``;失败静默(不影响主流程)。

    延迟 ``import`` diary_write 避免循环引用 (diary_tools 间接依赖 registry);
    try 范围只包住 ``diary_write()`` 一行,让 import 失败的栈能传到上层排查。

    Args:
        turn_id: 当前 turn 的时间格式 ID。
        user_text / final_content / actions / wall_ms / tokens_in /
        tokens_out / error: 见 :func:`_format_turn_diary_body` 的同名参数。

    Side effects:
        写入 ``diary/YYYY-MM-DD.md``;失败时静默吞掉异常。
    """
    from ..tools.diary_tools import diary_write
    body = _format_turn_diary_body(
        user_text, final_content, actions, wall_ms, tokens_in, tokens_out, error
    )
    try:
        diary_write(title=f"turn {turn_id}", body=body)
    except Exception:
        # 日志写入失败不该拖垮 turn 返回值;与原本 "except Exception: pass" 等价。
        pass


class ReActLoop:
    """主循环:组装 system prompt → 调 backend → 执行工具 → 写 trace/diary。

    所有依赖 (backend / registry / gate / recorder / memory / snapshot)
    都接受构造时注入,默认从 :mod:`xragent.config.settings` / 各模块
    默认工厂拉取,便于测试时替换为 mock。

    Attributes:
        settings: 配置单例 (来自 :func:`get_settings`)。
        backend: LLM 后端 (``None`` 时首次 :meth:`run` 才惰性创建)。
        registry: 工具注册表。
        gate: HITL 审批闸门。
        recorder: turn trace 写入器。
        memory: 上下文压缩管理器。
        snapshot: side-git 快照管理器。
        max_steps: 单轮最大推理步数;达到仍无 final content 视为超时。
        on_heartbeat: 心跳回调,每步调用一次 (供 supervisor 检测活体)。
        tag_snapshots: 是否给 snapshot 打 git tag。
    """

    def __init__(
        self, backend: BackendProtocol | None = None, registry: ToolRegistry | None = None,
        gate: HitlGate | None = None, recorder: TraceRecorder | None = None,
        memory: MemoryManager | None = None, snapshot: SideGit | None = None,
        max_steps: int = 16, on_heartbeat: Callable[[], None] | None = None,
        tag_snapshots: bool = True,
    ) -> None:
        """初始化 :class:`ReActLoop` 并实例化各依赖。

        Args:
            backend: LLM 后端; ``None`` 走 :func:`get_backend` 工厂。
            registry: 工具注册表; ``None`` 用 :func:`build_default_registry`。
            gate: HITL 审批闸门; ``None`` 用 :class:`HitlGate` 默认实例。
            recorder: turn trace 写入器; ``None`` 用 :class:`TraceRecorder`。
            memory: 上下文压缩管理器; ``None`` 用 :class:`MemoryManager`。
            snapshot: side-git 快照管理器; ``None`` 用 :class:`SideGit`。
            max_steps: 单轮最大步数,默认 16。
            on_heartbeat: 每步心跳回调; ``None`` 用 ``lambda: None`` 占位。
            tag_snapshots: 是否给 snapshot 打 tag;默认 True。
        """
        self.settings = get_settings()
        self.backend = backend
        self.registry = registry or build_default_registry()
        self.gate = gate or HitlGate()
        self.recorder = recorder or TraceRecorder()
        self.memory = memory or MemoryManager()
        self.snapshot = snapshot or SideGit()
        self.max_steps = max_steps
        self.on_heartbeat = on_heartbeat or (lambda: None)
        self.tag_snapshots = tag_snapshots

    def _ensure_backend(self) -> BackendProtocol:
        """惰性创建 ``self.backend`` 并返回。

        首次 :meth:`run` 调用时若 ``self.backend`` 为 ``None``,从
        :func:`get_backend` 工厂拉取;之后直接返回缓存对象。

        Returns:
            BackendProtocol: 可用的 LLM 后端实例。
        """
        if self.backend is None:
            from ..core.backend import get_backend
            self.backend = get_backend()
        return self.backend

    def _snapshot(self, turn_id: str, label: str, user_text: str) -> Snapshot:
        """封装 ``self.snapshot.snapshot`` 调用模板,统一 note 格式与 tag 策略。

        把 :meth:`SideGit.snapshot` 的两组 magic 元素 (note 模板 ``"<label>-turn:<前40字>"``
        与 ``tag=self.tag_snapshots``) 收敛到一处;Run 流程里只关心"什么时候
        打快照"和"哪个阶段",不重复写 kwarg。

        Args:
            turn_id: turn 时间格式 ID;post-turn 调用方追加 ``"-post"`` 后传入。
            label: 阶段标签,典型值 ``"pre"`` / ``"post"``,出现在 note 前缀。
            user_text: 当前 turn 用户输入;截断前 40 字符拼入 note。

        Returns:
            :class:`~xragent.snapshot.side_git.Snapshot`: 与
            :meth:`SideGit.snapshot` 一致。
        """
        return self.snapshot.snapshot(
            turn_id,
            note=f"{label}-turn:{user_text[:_USER_TEXT_NOTE_MAX]}",
            tag=self.tag_snapshots,
        )

    def run(self, user_text: str, session_messages: list[Message] | None = None) -> dict:
        """跑一轮 ReAct:装配 system prompt → 调 backend → 执行工具 → 收口。

        流程要点:
          * 若 ``session_messages`` 为空或首条非 system,自动在头部插入
            :func:`assemble_system_prompt` 构造的 system 消息;
          * 循环里先 :meth:`memory.compress_if_needed`,再 ``backend.chat``,
            有 ``tool_calls`` 就逐个通过 :meth:`registry.run` 执行并
            追加 tool 消息;
          * 超过 ``max_steps`` 仍无 final content 时, ``error`` 记为
            ``"max_steps=... 仍无 final content"``,返回字典而非抛异常。

        Args:
            user_text: 本轮用户输入。
            session_messages: 可选跨轮会话上下文; ``None`` 表示新会话。

        Returns:
            dict: ``turn_id`` / ``answer`` / ``actions`` / ``observations`` /
            ``tokens_in`` / ``tokens_out`` / ``wall_ms`` / ``error`` /
            ``snapshot`` (pre-turn 的 tag 名) 共 9 个键的结果字典。
        """
        backend = self._ensure_backend()
        s = self.settings
        turn_id = new_turn_id()
        snap = self._snapshot(turn_id, "pre", user_text)

        messages: list[Message] = session_messages or []
        if not messages or messages[0].role != "system":
            messages.insert(0, Message(role="system", content=assemble_system_prompt()))
        messages.append(Message(role="user", content=user_text))

        wall_start = time.time()
        tokens_in = 0
        tokens_out = 0
        actions = []
        observations = []
        final_content = ""
        error = None

        try:
            for step in range(self.max_steps):
                messages = self.memory.compress_if_needed(messages, s.context_budget_tokens, s.compress_target_ratio)
                self.on_heartbeat()
                turn = backend.chat(messages, self.registry.specs())
                tokens_in += turn.usage.get("prompt_tokens", 0)
                tokens_out += turn.usage.get("completion_tokens", 0)
                messages.append(make_assistant_message(turn))
                if not turn.tool_calls:
                    final_content = turn.content or ""
                    break
                for tc in turn.tool_calls:
                    self.on_heartbeat()
                    args = tc.args if isinstance(tc.args, dict) else {}
                    res = self.registry.run(tc.name, args, gate=self.gate)
                    actions.append({"step": step, "tool": tc.name, "args": args, "id": tc.id})
                    observations.append({"step": step, "tool": tc.name, "result": res, "id": tc.id})
                    messages.append(make_tool_message(tc.id or f"call_{step}_{tc.name}", res))
            else:
                error = f"max_steps={self.max_steps} 仍无 final content"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        wall_ms = int((time.time() - wall_start) * 1000)
        rec = TurnRecord(
            turn_id=turn_id, ts=wall_start,
            think=final_content or "(no final content)",
            action={"actions": actions}, observation={"observations": observations},
            tokens_in=tokens_in, tokens_out=tokens_out, wall_ms=wall_ms, error=error,
        )
        self.recorder.write(rec)

        _record_turn_diary(
            turn_id, user_text, final_content, actions,
            wall_ms, tokens_in, tokens_out, error,
        )

        self._snapshot(turn_id + "-post", "post", user_text)

        return {
            "turn_id": turn_id, "answer": final_content,
            "actions": actions, "observations": observations,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "wall_ms": wall_ms, "error": error, "snapshot": snap.tag,
        }