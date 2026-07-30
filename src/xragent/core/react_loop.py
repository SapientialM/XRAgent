"""ReAct 主循环。"""
from __future__ import annotations

import json
import time
from typing import Callable

from ..config.settings import get_settings
from ..core.backend import BackendProtocol, Message, ToolCall
from ..core.dream import assemble_system_prompt
from ..core.turn import TraceRecorder, TurnRecord, new_turn_id
from ..hitl.gate import HitlGate
from ..memory.manager import MemoryManager
from ..snapshot.side_git import SideGit
from ..tools.registry import ToolRegistry, build_default_registry


def make_tool_message(tool_call_id: str, content) -> Message:
    return Message(role="tool", content=json.dumps(content, ensure_ascii=False), tool_call_id=tool_call_id)


def make_assistant_message(turn) -> Message:
    return Message(role="assistant", content=turn.content or "", tool_calls=turn.tool_calls or None)


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
    def __init__(
        self, backend: BackendProtocol | None = None, registry: ToolRegistry | None = None,
        gate: HitlGate | None = None, recorder: TraceRecorder | None = None,
        memory: MemoryManager | None = None, snapshot: SideGit | None = None,
        max_steps: int = 16, on_heartbeat: Callable[[], None] | None = None,
        tag_snapshots: bool = True,
    ):
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
        if self.backend is None:
            from ..core.backend import get_backend
            self.backend = get_backend()
        return self.backend

    def run(self, user_text: str, session_messages: list[Message] | None = None) -> dict:
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

        self.snapshot.snapshot(turn_id + "-post", note=f"post-turn:{user_text[:40]}", tag=self.tag_snapshots)

        return {
            "turn_id": turn_id, "answer": final_content,
            "actions": actions, "observations": observations,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "wall_ms": wall_ms, "error": error, "snapshot": snap.tag,
        }