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
from ..snapshot.side_git import SideGit
from ..tools.registry import ToolRegistry, build_default_registry


def make_tool_message(tool_call_id: str, content: Any) -> Message:
    """把工具执行结果包装成 ``Message(role="tool")``。

    Args:
        tool_call_id: 关联的 assistant tool_call.id；用于多步 ReAct 时
            把 tool result 对齐到对应 tool_call。
        content: 工具返回（任意 JSON 可序列化对象）；会被 ``json.dumps``
            + ``ensure_ascii=False`` 序列化成字符串存到 ``Message.content``。

    Returns:
        构造好的 ``Message`` 实例，``role="tool"``，``content`` 为 JSON 串。
    """
    return Message(role="tool", content=json.dumps(content, ensure_ascii=False), tool_call_id=tool_call_id)


def make_assistant_message(turn: Any) -> Message:
    """把 backend 返回的 assistant turn 翻译成 ``Message``。

    Args:
        turn: backend chat() 返回的对象；需要支持 ``.content`` (str | None)
            和 ``.tool_calls`` (list | None)。

    Returns:
        ``Message(role="assistant", content=..., tool_calls=...)``。若
        ``turn.content`` 为 falsy 则存 ``""``；若 ``turn.tool_calls`` 为 falsy
        则存 ``None``（避免下游判 ``"non-empty list"`` 时误命中）。
    """
    return Message(role="assistant", content=turn.content or "", tool_calls=turn.tool_calls or None)


class ReActLoop:
    def __init__(
        self,
        backend: BackendProtocol | None = None,
        registry: ToolRegistry | None = None,
        gate: HitlGate | None = None,
        recorder: TraceRecorder | None = None,
        memory: MemoryManager | None = None,
        snapshot: SideGit | None = None,
        max_steps: int = 16,
        on_heartbeat: Callable[[], None] | None = None,
        tag_snapshots: bool = True,
    ) -> None:
        """组装 ReAct 依赖图：backend / tools / HITL gate / 记忆 / 快照。

        任意依赖为 ``None`` 时回退到默认实例（``build_default_registry()``、
        ``HitlGate()`` 等）。``on_heartbeat`` 默认 no-op，supervisor 注入后
        用来在长 turn 中刷"还活着"信号。

        Args:
            backend: LLM 后端；为 ``None`` 时在第一次 ``run()`` 时惰性
                ``get_backend()``。
            registry: 工具注册表；默认含全部内置工具。
            gate: HITL 审批门，详见 :mod:`xragent.hitl`。
            recorder: turn trace 写入器；trace 文件落 ``settings.turns_dir``。
            memory: 长期/短期记忆管理器。
            snapshot: git sidecar（每个 turn 打 tag + stash 备份）。
            max_steps: ReAct 最大步数，超出仍无 final content 视为失败。
            on_heartbeat: 长 turn 心跳回调；签名 ``() -> None``。
            tag_snapshots: 是否真的打 git tag（测试时可关）。
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
        """惰性初始化 ``self.backend``。

        ``__init__`` 不立即 ``get_backend()``，因为：
          - 单测通常注入 fake backend，触发 ``get_backend()`` 会读 env / 联网
          - 多次构造 ReActLoop 但本次不 ``run()`` 时，避免无谓副作用

        Returns:
            已经非空的 ``self.backend``（首次调用会赋值）。
        """
        if self.backend is None:
            from ..core.backend import get_backend
            self.backend = get_backend()
        return self.backend

    def run(self, user_text: str, session_messages: list[Message] | None = None) -> dict[str, Any]:
        """跑一轮 ReAct：snapshot → system+user 注入 → 循环 tool call → 收尾 snapshot。

        行为细节：
          * ``session_messages`` 缺 system 时自动前置 ``assemble_system_prompt()``
          * 每步先 ``memory.compress_if_needed`` 防 context 超 budget
          * ``max_steps`` 用尽仍无 final content → ``error`` 字段非空
          * turn 结束无论成败都 ``recorder.write`` + ``diary_write``（后者失败不阻断）
          * turn 开头/结尾各打一次 snapshot（开头 stash 备份 + tag，结尾 post-tag）

        Args:
            user_text: 用户本轮输入。
            session_messages: 可选会话上文；为 ``None`` 时从空 list 起。
                若首条不是 ``role="system"`` 会自动前置 system prompt。

        Returns:
            dict 字段：
              * turn_id, answer, actions, observations, tokens_in/out,
                wall_ms, error, snapshot (开头 snapshot tag 名)
        """
        backend = self._ensure_backend()
        s = self.settings
        turn_id = new_turn_id()
        snap = self.snapshot.snapshot(turn_id, note=f"pre-turn:{user_text[:40]}", tag=self.tag_snapshots)

        messages: list[Message] = session_messages or []
        if not messages or messages[0].role != "system":
            messages.insert(0, Message(role="system", content=assemble_system_prompt()))
        messages.append(Message(role="user", content=user_text))

        wall_start = time.time()
        tokens_in = 0
        tokens_out = 0
        actions: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        final_content = ""
        error: str | None = None

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
                    args: dict[str, Any] = tc.args if isinstance(tc.args, dict) else {}
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

        try:
            from ..tools.diary_tools import diary_write
            diary_write(
                title=f"turn {turn_id}",
                body=(
                    f"**输入**: {user_text[:200]}\n\n"
                    f"**回答**: {final_content[:400]}\n\n"
                    f"**动作**: {[a['tool'] for a in actions]}\n\n"
                    f"**耗时**: {wall_ms}ms · tokens_in={tokens_in} tokens_out={tokens_out}\n"
                    + (f"**错误**: {error}" if error else "")
                ),
            )
        except Exception:
            pass

        self.snapshot.snapshot(turn_id + "-post", note=f"post-turn:{user_text[:40]}", tag=self.tag_snapshots)

        return {
            "turn_id": turn_id, "answer": final_content,
            "actions": actions, "observations": observations,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "wall_ms": wall_ms, "error": error, "snapshot": snap.tag,
        }