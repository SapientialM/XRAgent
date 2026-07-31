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


def _safe_call(
    handler: Callable[..., dict[str, Any]], args: dict[str, Any]
) -> dict[str, Any]:
    """调用 ``handler(**args)`` 并把任意异常包成 ``{"ok": False, "error": ...}`` envelope。

    抽出来原因: :meth:`ToolRegistry.run` 里原本内嵌 ``try/except`` 块,
    handler 一多就重复; 而且 HITL 之外的执行路径 (e.g. 未来直接 ``dispatch``
    给 LLM 调用 handler) 也想复用同一份异常契约, 集中到一处。

    行为约定:
      * handler 正常返回 → 透传 (不强制 ``ok`` 键, 因为 handler 自签契约);
      * handler 抛 ``Exception`` → ``{"ok": False, "error": "<TypeName>: <msg>"}``
        —— 与旧 ``ToolRegistry.run`` 内部 try/except 完全等价, 保证
        test_registry 中 ``test_run_handler_exception_is_swallowed_with_error_envelope``
        等历史断言不破;
      * ``BaseException`` (KeyboardInterrupt / SystemExit) 不吞, 让 supervisor
        接管——避免误吞中断信号导致 Agent 失控。

    Args:
        handler: 已注册的 tool handler, 签名 ``(**args) -> dict[str, Any]``。
        args: 透传给 handler 的 kwargs; 空 dict 时等价于 ``handler()``。

    Returns:
        dict[str, Any]: handler 原返回值, 或异常 envelope。
    """
    try:
        return handler(**args)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class ToolRegistry:
    """工具注册中心 —— ``ToolDef`` 的 dict 容器 + HITL gate 调度。

    通过 :meth:`register` / :meth:`unregister` 维护 ``self._tools``；
    :meth:`run` 是统一的执行入口，先走 :func:`_apply_hitl` 再调 handler，
    handler 异常统一包成 ``{"ok": False, "error": ...}`` envelope。
    """

    def __init__(self) -> None:
        """初始化空的 ``self._tools: dict[str, ToolDef]``。"""
        self._tools: dict[str, ToolDef] = {}

    def register(self, t: ToolDef) -> None:
        """注册一个 :class:`ToolDef`。

        Args:
            t: 工具定义；``t.name`` 必须唯一。

        Raises:
            ValueError: ``t.name`` 已注册（避免静默覆盖）。
        """
        if t.name in self._tools:
            raise ValueError(f"重复注册: {t.name}")
        self._tools[t.name] = t

    def unregister(self, name: str) -> None:
        """注销一个工具；不存在则静默 no-op（与 :meth:`dict.pop` 默认行为一致）。

        Args:
            name: 工具名。
        """
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef:
        """按名取 :class:`ToolDef`（同步访问点；:meth:`run` 内部也走这里）。

        Args:
            name: 工具名。

        Returns:
            ToolDef: 已注册的同名工具定义。

        Raises:
            KeyError: ``name`` 不在注册表里（与 :meth:`dict.__getitem__` 语义一致；
                :meth:`run` 会把这条异常透给调用方，由调用方决定是否包 envelope）。
        """
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        """已注册的工具名列表（插入序；新 list，不暴露内部 dict）。"""
        return list(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        """把已注册工具转成 :class:`ToolSpec` 列表（用于 LLM function-calling 描述）。

        Returns:
            list[ToolSpec]: ``name``/``description``/``input_schema``/``risk`` 四元组；
            不含 handler（不暴露代码给外部）。
        """
        return [
            ToolSpec(name=t.name, description=t.description, input_schema=t.input_schema, risk=t.risk)
            for t in self._tools.values()
        ]

    def run(self, name: str, args: dict[str, Any], gate: Any = None) -> dict[str, Any]:
        """统一执行入口：HITL gate → handler → 异常包络。

        流程:
          1. :meth:`get` 取 :class:`ToolDef`（未知工具抛 KeyError）；
          2. :func:`_apply_hitl` 决定 ``args`` / ``approved`` / ``rejected``；
          3. 若 ``rejected`` 非 None，直接返回 ``{"ok": False, "blocked_by": "hitl", "reason": ...}``；
          4. 否则 :func:`_safe_call` 调 handler 并包异常 envelope；
          5. 若 ``approved``，在结果 dict 上加 ``hitl_approved: True``。

        Args:
            name: 工具名。
            args: 透传给 handler 的 kwargs；HITL EDIT 时会被替换。
            gate: HITL gate；callable 或有 ``.request(req)`` 方法的对象；None 跳过审批（仅 low/medium）。

        Returns:
            dict[str, Any]: handler 返回值或包络；``ok`` 键必有。
        """
        td = self.get(name)
        outcome = _apply_hitl(name, td, args, gate)
        if outcome.rejected is not None:
            return {"ok": False, "blocked_by": "hitl", "reason": outcome.rejected.reason}
        # _safe_call 已吞 Exception (除 BaseException), 不再需要外层 try/except
        out = _safe_call(td.handler, outcome.args)
        if outcome.approved:
            out = {"ok": out.get("ok", True), **out, "hitl_approved": True}
        return out


def build_default_registry() -> ToolRegistry:
    """构造默认 :class:`ToolRegistry`，注册所有内置工具。

    注册表（按风险级别）：
      * low: read_file / list_dir / memory_save / memory_recall /
        memory_recall_range / memory_top_frequent / memory_recall_by_tag /
        diary_write
      * medium: curl_url / web_search / snapshot_cleanup
      * high: write_file / run_cmd / git_commit / git_push /
        propose_self_replace / terminate（需 HITL 审批）

    若 :attr:`Settings.evolution_enabled` 为 False，自动 ``unregister`` 掉
    ``propose_self_replace`` 与 ``terminate``（避免自进化通道被误用）。

    Returns:
        ToolRegistry: 全新实例；调用方可继续 :meth:`ToolRegistry.register` / :meth:`ToolRegistry.unregister`。
    """
    from . import fs_tools, exec_tools, git_tools, memory_tools, diary_tools, evolve_tools
    from ..config.settings import get_settings

    r = ToolRegistry()

    def add(name: str, desc: str, schema: dict[str, Any], risk: str, fn: Callable[..., dict[str, Any]]) -> None:
        """便捷注册助手 —— 语法糖：构造 :class:`ToolDef` 并 register。

        Args:
            name: 工具名。
            desc: LLM 可见的人类描述。
            schema: JSON Schema for tool args。
            risk: ``"low"`` / ``"medium"`` / ``"high"``，决定 HITL 是否拦截。
            fn: 实际 handler；返回 ``dict[str, Any]`` envelope。
        """
        r.register(ToolDef(name=name, description=desc, input_schema=schema, risk=risk, handler=fn))

    add("read_file", "读取仓库内文本文件，可选 max_bytes 截断（仅返回首 N 字节；超出时 truncated=True）。返回字段含 original_size（文件原始字节数，恒报）与 size（返回字符数）。硬上限 MAX_READ_BYTES (默认 200KB): 超过时直接 ok=False 拒绝, 带 size/limit 字段; max_bytes 显式时优先, 不走硬上限。",
        {"type": "object", "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer", "minimum": 1,
                          "description": "可选字节上限；None / 0 / 负数 / 非 int → 不截断（向后兼容）。显式时优先于 MAX_READ_BYTES。"},
        }, "required": ["path"]},
        "low", fs_tools.read_file)
    add("list_dir", "列出仓库内目录内容（不含 .git）。",
        {"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
        "low", fs_tools.list_dir)
    add("write_file", "在仓库内创建/覆盖文件；目标必须经过路径围栏与黑名单校验。content 必须是 str, 超 MAX_WRITE_BYTES (默认 1MB) 拒绝。需要 HITL 审批。",
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
    add("snapshot_cleanup", "清理 N 天前的 xragent/turn-* snapshot tag（仅本地，不走网络，可恢复）。默认 30 天；max_age_days<=0 禁用；dry_run=True 仅列候选。",
        {"type": "object", "properties": {
            "max_age_days": {"type": "integer", "description": "保留天数；None 走 settings.snapshot_retention_days；<=0 禁用"}, 
            "dry_run": {"type": "boolean", "default": False, "description": "True 仅列候选 tag 不实际删除"},
        }},
        "medium", git_tools.snapshot_cleanup)
    add("memory_save", "向长期记忆写入一条 fact（SQLite）。",
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
    add("memory_recall_by_tag", "按 tag 跨 category 横向召回 fact (newest first)，tag 空时返回空。",
        {"type": "object", "properties": {
            "tag": {"type": "string", "description": "目标 tag 字符串；空字符串会被 wrapper 拦截, 直接返回空结果"},
            "k": {"type": "integer", "default": 10, "description": "最多返回条数; clip 到 [1, 1000]"},
        }, "required": ["tag"]},
        "low", memory_tools.memory_recall_by_tag)
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