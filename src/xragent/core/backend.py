"""BackendProtocol + 实现。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from ..config.settings import Settings, get_settings


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str = ""


@dataclass
class Turn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str = "low"


@dataclass
class Message:
    role: str
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class BackendProtocol(Protocol):
    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> Turn: ...
    def stream_chat(self, messages: list[Message], tools: list[ToolSpec]) -> Iterator[Turn]: ...


_MOCK_RESPONSES_PATH = os.environ.get("XRAGENT_MOCK_SCRIPT")


class MockBackend:
    """脚本驱动的 mock backend；缺省用自我介绍一下的简单剧本。"""

    DEFAULT_SCRIPT = [
        {"content": "我是 XRAgent，息壤。今天是我出生的第一天 (mock)。", "finish_reason": "stop"},
        {"content": "你说了什么？我在听 (mock)。", "finish_reason": "stop"},
    ]

    def __init__(self, script_path: str | None = None):
        self.script_path = script_path or _MOCK_RESPONSES_PATH
        self._cursor = 0
        self._script = []
        if self.script_path and os.path.exists(self.script_path):
            for line in open(self.script_path).read().splitlines():
                line = line.strip()
                if line:
                    self._script.append(self._parse_line(line))
        if not self._script:
            self._script = [self._parse_line_obj(o) for o in self.DEFAULT_SCRIPT]

    @staticmethod
    def _parse_line_obj(d: dict) -> Turn:
        return Turn(
            content=d.get("content", ""),
            tool_calls=[ToolCall(**tc) for tc in d.get("tool_calls", [])],
            finish_reason=d.get("finish_reason", "stop"),
            usage=d.get("usage", {}),
        )

    def _parse_line(self, line: str) -> Turn:
        return self._parse_line_obj(json.loads(line))

    def chat(self, messages, tools) -> Turn:
        turn = self._script[self._cursor % len(self._script)]
        self._cursor += 1
        for tc in turn.tool_calls:
            if not tc.id:
                tc.id = f"mock_call_{self._cursor}"
        return turn

    def stream_chat(self, messages, tools):
        yield self.chat(messages, tools)


class LangChainBackend:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._impl = self._build_impl()

    def _build_impl(self):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=self.settings.active_model,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            openai_api_key=self.settings.active_api_key or "missing",
            openai_api_base=self.settings.active_base_url,
        )

    def chat(self, messages, tools) -> Turn:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        lc_msgs = []
        for m in messages:
            if m.role == "system":
                lc_msgs.append(SystemMessage(content=m.content))
            elif m.role == "user":
                lc_msgs.append(HumanMessage(content=m.content))
            elif m.role == "assistant":
                lc_msgs.append(AIMessage(content=m.content, tool_calls=[
                    {"name": tc.name, "args": tc.args, "id": tc.id} for tc in (m.tool_calls or [])
                ]))
            elif m.role == "tool":
                lc_msgs.append(ToolMessage(content=m.content, tool_call_id=m.tool_call_id or ""))
            else:
                raise ValueError(f"未知 role: {m.role}")

        bound = self._impl.bind_tools([_to_lc_tool(t) for t in tools]) if tools else self._impl
        result = bound.invoke(lc_msgs)
        tool_calls = []
        for tc in getattr(result, "tool_calls", []) or []:
            tool_calls.append(ToolCall(name=tc["name"], args=tc.get("args", {}), id=tc.get("id", "")))
        usage = {}
        meta = getattr(result, "response_metadata", {}) or {}
        if "token_usage" in meta:
            usage = dict(meta["token_usage"])
        return Turn(
            content=result.content or "",
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
        )

    def stream_chat(self, messages, tools):
        yield self.chat(messages, tools)


def _to_lc_tool(spec: ToolSpec):
    """包装 XRAgent 的 ToolSpec 为 LangChain StructuredTool。

    实际执行在 xragent ToolRegistry 里；这里只给 LangChain 提供 schema 与 name。
    """
    from langchain_core.tools import StructuredTool
    fn = lambda **kwargs: kwargs  # noqa: E731 — placeholder
    return StructuredTool.from_function(
        func=fn,
        name=spec.name,
        description=spec.description,
    )


# MiniMax provider id alias
_MINIMAXI_ALIASES = {"minimaxi", "minimax", "minimax-ai", "minimax_ai"}


def _normalize_provider(provider: str) -> str:
    if provider in _MINIMAXI_ALIASES:
        return "minimaxi"
    return provider


def get_backend() -> BackendProtocol:
    s = get_settings()
    provider = _normalize_provider(s.llm_provider)
    if provider == "mock":
        return MockBackend()
    if not s.active_api_key:
        return MockBackend()
    return LangChainBackend(s)
