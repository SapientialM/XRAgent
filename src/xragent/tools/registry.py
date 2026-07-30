"""ToolRegistry：工具注册中心。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

from ..core.backend import ToolSpec
from . import web_search  # curl_url + web_search tools


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str
    handler: Callable[..., dict[str, Any]]


class _HitlRejected:
    """HITL 拒绝的轻量哨兵：避免把 rejection 走 handler 异常分支。"""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason


class _HitlOutcome(NamedTuple):
    """`_apply_hitl` 的返回：args（可能被 EDIT 改过）、approved 旗标、可选 rejection 哨兵。"""

    args: dict[str, Any]
    approved: bool
    rejected: _HitlRejected | None  # 非 None 表示调用方应直接返回 blocked envelope


def _call_gate(gate: Any, req: Any) -> Any:
    """兼容 callable gate 与有 .request() 方法的 gate 对象（如 HitlGate）。"""
    request = getattr(gate, "request", None)
    if callable(request):
        return request(req)
    return gate(req)


def _apply_hitl(name: str, td: ToolDef, args: dict[str, Any], gate: Any) -> _HitlOutcome:
    """低风险 / gate=None 时直通；高风险走审批，根据 Decision 返回编辑后的 args + 旗标。"""
    if td.risk != "high" or gate is None:
        return _HitlOutcome(args=args, approved=False, rejected=None)

    from ..hitl.gate import ApprovalRequest, ApprovalResult, Decision  # lazy import
    req = ApprovalRequest(
        tool_name=name, tool_args=args, risk=td.risk,
        summary=f"{name}({list(args.keys())})", tool_call_id=name,
    )
    res = _call_gate(gate, req)
    if res.decision == Decision.REJECT:
        return _HitlOutcome(args=args, approved=False, rejected=_HitlRejected(res.reason))
    if res.decision == Decision.EDIT and res.edited_args:
        args = res.edited_args
    return _HitlOutcome(args=args, approved=True, rejected=None)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, t: ToolDef) -> None:
        if t.name in self._tools:
            raise ValueError(f"重复注册: {t.name}")
        self._tools[t.name] = t

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[t.name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=t.name, description=t.description, input_schema=t.input_schema, risk=t.risk)
            for t in self._tools.values()
        ]

    def run(self, name: str, args: dict[str, Any], gate=None) -> dict[str, Any]:
        td = self.get(name)
        outcome = _apply_hitl(name, td, args, gate)
        if outcome.rejected is not None:
            return {"ok": False, "blocked_by": "hitl", "reason": outcome.rejected.reason}
        try:
            out = td.handler(**outcome.args)
        except Exception as e:
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if outcome.approved:
            out = {"ok": out.get("ok", True), **out, "hitl_approved": True}
        return out


def build_default_registry() -> ToolRegistry:
    from . import fs_tools, exec_tools, git_tools, memory_tools, diary_tools, evolve_tools
    from ..config.settings import get_settings

    r = ToolRegistry()

    def add(name, desc, schema, risk, fn):
        r.register(ToolDef(name=name, description=desc, input_schema=schema, risk=risk, handler=fn))

    add("read_file", "读取仓库内文件内容；目标必须位于仓库根之下。",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        "low", fs_tools.read_file)
    add("list_dir", "列出仓库内目录内容（不含 .git）。",
        {"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
        "low", fs_tools.list_dir)
    add("write_file", "在仓库内创建/覆盖文件；目标必须经过路径围栏与黑名单校验。需要 HITL 审批。",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        "high", fs_tools.write_file)
    add("run_cmd", "在仓库根执行 shell 命令；30s 超时；走 binary 黑名单。需要 HITL 审批。",
        {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
        "high", exec_tools.run_cmd)
    add("git_commit", "对仓库内当前变更做 git add+commit；返回 commit hash。需要 HITL 审批。",
        {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        "high", git_tools.git_commit)
    add("git_push", "git push 到 origin/<branch>；网络失败或超时时返回错误。默认 30s 超时。需要 HITL 审批。",
        {"type": "object", "properties": {
            "remote": {"type": "string", "default": "origin"},
            "branch": {"type": "string", "default": "main"},
            "timeout_s": {"type": "number", "default": 30, "description": "push 超时秒数；None / 非正数 / 非数值 → 默认 30s"},
        }},
        "high", git_tools.git_push)
    add("memory_save", "向长期记忆写入一条事实（SQLite）。",
        {"type": "object", "properties": {"category": {"type": "string"}, "content": {"type": "string"}}, "required": ["category", "content"]},
        "low", memory_tools.memory_save)
    add("memory_recall", "关键词 LIKE 召回 fact (newest first)，回答我说过什么关于 X 的事。query 空时退化为全量最新 k 条。",
        {"type": "object", "properties": {
            "query": {"type": "string", "default": ""},
            "k": {"type": "integer", "default": 5},
            "category": {"type": "string"},
        }},
        "low", memory_tools.memory_recall)
    add("memory_recall_range", "按时间窗口从长期记忆召回 fact (newest first)。start_ts/end_ts 为 None 时表示开放端。",
        {"type": "object", "properties": {
            "start_ts": {"type": "number"},
            "end_ts": {"type": "number"},
            "category": {"type": "string"},
            "k": {"type": "integer", "default": 1000},
        }},
        "low", memory_tools.memory_recall_range)
    add("memory_top_frequent", "按 content 频次降序返回 top-N；min_count 过滤一次性噪音。",
        {"type": "object", "properties": {
            "n": {"type": "integer", "default": 10},
            "category": {"type": "string"},
            "min_count": {"type": "integer", "default": 2},
        }},
        "low", memory_tools.memory_top_frequent)
    add("diary_write", "向 diary/YYYY-MM-DD.md 追加一段（人类可读）。",
        {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title", "body"]},
        "low", diary_tools.diary_write)
    add("propose_self_replace", "金蝉脱壳：commit → push → 编译 → supervisor 切换。需要 HITL 审批。",
        {"type": "object", "properties": {"reason": {"type": "string"}, "entry": {"type": "string", "default": "src/xragent/main.py"}}, "required": ["reason"]},
        "high", evolve_tools.propose_self_replace)
    add("curl_url", "抓取 URL 内容（GET/POST），自动写 diary/search-log.md。敏感词拦截。",
        {"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string", "default": "GET"}, "data": {"type": "string", "default": ""}}, "required": ["url"]},
        "medium", web_search.curl_url)
    add("web_search", "用 DuckDuckGo 搜索 query（无需 API key），返回 top 5 URL。",
        {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}}, "required": ["query"]},
        "medium", web_search.web_search)
    add("terminate", "优雅终止当前 Agent 进程；supervisor 不会再自动拉起。需要 HITL 审批。",
        {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
        "high", evolve_tools.terminate)

    s = get_settings()
    if not s.evolution_enabled:
        r.unregister("propose_self_replace")
        r.unregister("terminate")
    return r
