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
    """LLM backend 实现的最小契约。

    上层 Agent 通过该 Protocol 拿到 backend，不绑具体实现；任何满足
    ``chat`` / ``stream_chat`` 签名的对象都可注入。
    """

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> Turn:
        """一次性 chat 调用: 接收完整消息历史 + 工具规范, 返回一条 Turn。

        实现方应把 ``messages`` 转为自家 backend（LangChain / mock /
        minimaxi 等）的内部格式, 调一次 LLM 后包成 :class:`Turn` 返回;
        ``tool_calls`` 缺 ``id`` 时由实现方负责补全, 调用方不做假设。

        Args:
            messages: 当前会话消息序列；至少含 1 条 system prompt。
            tools: 可用工具规范列表；非空时按 ``tool_choice`` 协议注入
                给模型。

        Returns:
            Turn: 单轮响应（含 ``content`` / ``tool_calls`` / ``usage``）。
        """
        ...

    def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> Iterator[Turn]:
        """流式 chat: 返回 ``Turn`` 迭代器。

        流式协议：调用方按 ``finish_reason`` 决定是否停止迭代；通常
        ``"stop"`` 表示正常结束, ``"tool_calls"`` 表示有工具调用。
        mock backend 也只 ``yield`` 一条完整 Turn, 以保持签名一致。

        Args:
            messages: 同 :meth:`chat`。
            tools: 同 :meth:`chat`。

        Yields:
            Turn: 增量响应片段；至少 ``yield`` 一次。
        """
        ...


_MOCK_RESPONSES_PATH = os.environ.get("XRAGENT_MOCK_SCRIPT")


class MockBackend:
    """脚本驱动的 mock backend；缺省用自我介绍一下的简单剧本。"""

    DEFAULT_SCRIPT = [
        {"content": "我是 XRAgent，息壤。今天是我出生的第一天 (mock)。", "finish_reason": "stop"},
        {"content": "你说了什么？我在听 (mock)。", "finish_reason": "stop"},
    ]

    def __init__(self, script_path: str | None = None) -> None:
        """初始化 mock backend 并预加载剧本。

        加载顺序:
          * ``XRAGENT_MOCK_SCRIPT`` 环境变量 > 显式 ``script_path``;
          * 文件存在时按行 ``json.loads`` 后追加到 ``self._script``;
          * 文件为空 / 不存在 / 解析全失败时回退到 :data:`DEFAULT_SCRIPT`。

        Args:
            script_path: 覆盖环境变量的剧本路径; ``None`` 时用
                ``XRAGENT_MOCK_SCRIPT`` 或 ``DEFAULT_SCRIPT``。

        Side effects:
            设置 ``self.script_path`` / ``self._cursor`` / ``self._script``;
            任何 IO / 解析异常会让 :data:`DEFAULT_SCRIPT` 兜底,不会抛错。
        """
        self.script_path = script_path or _MOCK_RESPONSES_PATH
        self._cursor = 0
        if self.script_path and os.path.exists(self.script_path):
            # ``with`` + 显式 ``encoding="utf-8"``: 修 file handle 泄漏 +
            # 兼容 BOM (边界条件: Windows 记事本 / Excel 导出可能带 BOM)。
            # list comp 里用 walrus ``:=`` 把 strip 结果绑到 ``line``, 空行被过滤,
            # 坏行仍走 ``json.loads`` 抛 JSONDecodeError (锁 ``test_invalid_json_line_raises``)。
            with open(self.script_path, encoding="utf-8") as f:
                self._script = [
                    self._parse_line(line)
                    for raw in f
                    if (line := raw.strip())
                ]
        else:
            self._script = []
        if not self._script:
            self._script = [self._parse_line_obj(o) for o in self.DEFAULT_SCRIPT]

    @staticmethod
    def _parse_line_obj(d: dict) -> Turn:
        """把剧本 dict 解析成 :class:`Turn`。

        这是 ``_parse_line`` 与 ``DEFAULT_SCRIPT`` 共用的纯数据转换,
        抽出来便于两条路径在缺字段时回落到一致的默认值。

        Args:
            d: 单条剧本条目, 期望含 ``content`` / ``tool_calls`` /
                ``finish_reason`` / ``usage``, 字段缺失时用空值。

        Returns:
            Turn: 完整字段的 Turn; ``tool_calls`` 列表里的每个元素
                按 ``ToolCall(**tc)`` 展开, 字段名不匹配会抛 ``TypeError``。
        """
        return Turn(
            content=d.get("content", ""),
            tool_calls=[ToolCall(**tc) for tc in d.get("tool_calls", [])],
            finish_reason=d.get("finish_reason", "stop"),
            usage=d.get("usage", {}),
        )

    def _parse_line(self, line: str) -> Turn:
        """把剧本文件中的一行 JSON 解析为 :class:`Turn`。

        ``line`` 必须是合法 JSON object 字符串, 空行在 ``__init__`` 的
        list comp 里已被 walrus 过滤掉, 这里不再处理。

        Args:
            line: 已经 ``strip()`` 过的非空行, 内容为 JSON object。

        Returns:
            Turn: 经 :meth:`_parse_line_obj` 转换后的 Turn。

        Raises:
            json.JSONDecodeError: ``line`` 不是合法 JSON (由 ``json.loads`` 抛出)。
        """
        return self._parse_line_obj(json.loads(line))

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> Turn:
        """按 ``self._cursor`` 轮询 ``self._script`` 返回下一条 Turn。

        自动给 ``tool_calls`` 里 id 为空的项补 ``mock_call_<n>`` (n 是
        当前 cursor+1,避免与下次调用冲突)。

        Args:
            messages: 当前会话消息列表; mock 不消费,仅占位签名。
            tools: 当前可用工具规范列表; mock 不消费,仅占位签名。

        Returns:
            Turn: 剧本中下一条预录响应。
        """
        turn = self._script[self._cursor % len(self._script)]
        self._cursor += 1
        for tc in turn.tool_calls:
            if not tc.id:
                tc.id = f"mock_call_{self._cursor}"
        return turn

    def stream_chat(self, messages: list[Message], tools: list[ToolSpec]) -> Iterator[Turn]:
        """流式返回 mock 响应 —— 实际一次性 ``yield`` 一条 Turn。

        签名与 LangChain backend 对齐,即使 mock 不真的"流",也能让
        上层用同一份代码路径处理两种 backend。

        Args:
            messages: 同 :meth:`chat`。
            tools: 同 :meth:`chat`。

        Yields:
            Turn: 剧本中的下一条 Turn (仅一条)。
        """
        yield self.chat(messages, tools)


class LangChainBackend:
    """基于 LangChain ChatOpenAI 的 backend,生产环境用。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """加载配置并立刻构造 :class:`ChatOpenAI` 客户端。

        Args:
            settings: 配置单例; ``None`` 时通过 :func:`get_settings` 取。
                任意 :class:`Settings` 都必须含 ``active_api_key`` /
                ``active_base_url`` / ``active_model`` / ``llm_temperature``
                / ``llm_max_tokens`` 字段 (见 :class:`Settings` 定义)。

        Side effects:
            立刻调用 :meth:`_build_impl`,可能触发 ``langchain_openai``
            的导入 (重操作,首次启动有 ~200ms 延迟)。
        """
        self.settings = settings or get_settings()
        self._impl = self._build_impl()

    def _build_impl(self) -> Any:
        """构造底层 LangChain ``ChatOpenAI`` 客户端。

        Returns:
            Any: :class:`langchain_openai.ChatOpenAI` 实例 (返回 ``Any``
                以避免在模块顶部 ``import langchain_openai``,加重型依赖)。
        """
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=self.settings.active_model,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            openai_api_key=self.settings.active_api_key or "missing",
            openai_api_base=self.settings.active_base_url,
        )

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> Turn:
        """把 XRAgent 消息格式转 LangChain 格式后调一次 LLM。

        role 映射: ``system→SystemMessage`` / ``user→HumanMessage`` /
        ``assistant→AIMessage`` / ``tool→ToolMessage``;未知 role 直接
        :class:`ValueError` 抛错,让调用方立刻感知协议漂移。

        Args:
            messages: 待发消息序列;首条建议为 system prompt。
            tools: 可用工具规范列表;非空时通过 ``bind_tools`` 注入。

        Returns:
            Turn: ``content`` 为模型文本, ``tool_calls`` 从
                ``result.tool_calls`` 抽取, ``usage`` 从
                ``response_metadata.token_usage`` 抽取。
        """
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

    def stream_chat(self, messages: list[Message], tools: list[ToolSpec]) -> Iterator[Turn]:
        """流式接口 —— 当前实现与 :meth:`chat` 等价,只 ``yield`` 一次。

        与 mock backend 行为对齐,等 LangChain 真流式接入后再改。

        Args:
            messages: 同 :meth:`chat`。
            tools: 同 :meth:`chat`。

        Yields:
            Turn: 一次性产出当前轮的完整 Turn。
        """
        yield self.chat(messages, tools)


def _to_lc_tool(spec: ToolSpec) -> Any:
    """包装 XRAgent 的 ToolSpec 为 LangChain StructuredTool。

    用 Pydantic 模型作为 args_schema；这样 LangChain 不会把参数打包成 kwargs dict，
    而是按 schema 字段名正确展开。

    Args:
        spec: XRAgent 工具规范, ``input_schema`` 应为 JSON Schema 形
            ``{"type": "object", "properties": {...}, "required": [...]}``。

    Returns:
        Any: :class:`langchain_core.tools.StructuredTool` 实例 (返回 ``Any``
            因为 ``StructuredTool`` 仅在函数内导入)。
    """
    from langchain_core.tools import StructuredTool
    from pydantic import Field, create_model

    schema = spec.input_schema or {"type": "object", "properties": {}}
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])

    field_defs: dict[str, tuple] = {}
    for pname, pschema in props.items():
        desc = pschema.get("description", "") if isinstance(pschema, dict) else ""
        if pname in required:
            field_defs[pname] = (Any, Field(description=desc))
        else:
            default = pschema.get("default", None) if isinstance(pschema, dict) else None
            field_defs[pname] = (Any, Field(default=default, description=desc))

    if not field_defs:
        # 无参数工具：构造一个 dummy field 以满足 Pydantic
        field_defs = {"_": (Any, Field(default=None, description=""))}

    ArgsModel = create_model(f"{spec.name}_args", **field_defs)

    def _placeholder(**kwargs: Any) -> dict[str, Any]:
        """``StructuredTool`` 占位函数:收下 kwargs 后原样返回,不真执行。

        Args:
            **kwargs: 由 LangChain 按 ``ArgsModel`` 字段展开后的参数。

        Returns:
            dict[str, Any]: 原样返回 ``kwargs``,供上层 LLM 看参数示例。
        """
        return kwargs

    return StructuredTool.from_function(
        func=_placeholder,
        name=spec.name,
        description=spec.description,
        args_schema=ArgsModel,
    )


# MiniMax provider id alias
_MINIMAXI_ALIASES = {"minimaxi", "minimax", "minimax-ai", "minimax_ai"}


def _normalize_provider(provider: str) -> str:
    """把 provider 别名统一映射到 ``"minimaxi"`` 规范名。

    历史注册时曾用过 ``"minimax"`` / ``"minimax-ai"`` / ``"minimax_ai"``,
    全部视为同一家的别名,避免上游改名后还要逐处替换。

    Args:
        provider: 原始 provider 字符串 (来自 settings / 环境变量)。

    Returns:
        str: 命中别名集合时返回 ``"minimaxi"``,否则原样返回。
    """
    if provider in _MINIMAXI_ALIASES:
        return "minimaxi"
    return provider


def get_backend() -> BackendProtocol:
    """根据 settings 选 mock / 真实 backend。

    决策顺序:
      * provider 显式为 ``"mock"`` → :class:`MockBackend`;
      * ``active_api_key`` 为空 → :class:`MockBackend` (无 key 调不通,直接 mock);
      * 其它 → :class:`LangChainBackend` (走 LangChain ChatOpenAI)。

    Returns:
        BackendProtocol: 满足协议的后端实例,直接 ``chat`` / ``stream_chat`` 即可。
    """
    s = get_settings()
    provider = _normalize_provider(s.llm_provider)
    if provider == "mock":
        return MockBackend()
    if not s.active_api_key:
        return MockBackend()
    return LangChainBackend(s)