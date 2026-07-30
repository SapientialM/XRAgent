"""极简 HTTP 父母通道（可选）。"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, Callable

from .config.settings import get_settings

if TYPE_CHECKING:
    from .core.react_loop import ReActLoop


_shared_input_queue: "queue.Queue | None" = None
_last_answer_box: "dict | None" = None
_http_reply_queue: "queue.Queue[dict]" = queue.Queue()
_loop_ref: list = []

# HTTP 父母通道常量
# _http_approval_channel 等父母审批回复的最大等待时间；超时返回 REJECT。
HTTP_REPLY_TIMEOUT_S: float = 120.0
# /message 入队回执里截取的文本长度（避免长消息把响应体撑爆）。
_TEXT_PREVIEW_CHARS: int = 80


def register_input_queue(q: "queue.Queue") -> None:
    """注册共享输入队列（供 main.py 在启动时调用一次）。

    之后 HTTP ``POST /message`` 会把父母消息 ``put`` 到该队列。
    模块内只持有引用；生命周期与进程一致，不做 close。

    Args:
        q: 进程级共享队列，元素为 ``str``（原始父母消息文本）。
    """
    global _shared_input_queue
    _shared_input_queue = q


def register_answer_sink(box: dict) -> None:
    """注册最近一次 LLM answer 的容器（供 main.py 在启动时调用一次）。

    ``box`` 形如 ``{"answer": str, "ts": float}``，由 main 在每轮 React 后就地
    更新；HTTP ``GET /last-answer`` 直接读它（避免跨线程同步问题）。

    Args:
        box: 可变 dict 容器；key 至少含 ``answer``、``ts``。
    """
    global _last_answer_box
    _last_answer_box = box


def enqueue_message(text: str) -> None:
    """把人类父母消息塞进共享输入队列。

    Args:
        text: 原始消息文本；调用方应自行 ``strip()``。

    Raises:
        RuntimeError: 共享队列还没注册（main.py 没启动）。
    """
    if _shared_input_queue is not None:
        _shared_input_queue.put(text)
    else:
        raise RuntimeError("input queue 未注册；用 xragent.main --serve 启动")


def _coerce_text(value: Any) -> str:
    """把 JSON 字段值兜底成 strip 过的字符串。

    之前 do_POST 直接写 ``(body.get("text") or "").strip()``——对 ``"foo"`` /
    ``None`` 工作正常，但 ``{"text": 123}`` / ``{"text": ["x"]}`` 时
    ``int.strip`` / ``list.strip`` 会 AttributeError 冒泡到 HTTP 层（500），
    攻击者或前端 bug 都能触发。统一收敛：None → ""；str → strip；其他类型
    走 ``str(...)`` 再 strip。

    Args:
        value: ``body.get(...)`` 的原始 JSON 反序列化值（任意类型）。

    Returns:
        strip 后的字符串；空字符串表示调用方应判 400。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _coerce_content_length(raw: str | None) -> int:
    """解析 Content-Length 头，失败/缺失返回 0（让上层走空 body 路径）。

    ``self.headers.get("Content-Length", "0")`` 是字符串，原代码直接
    ``int(...)`` 在客户端发 ``"abc"`` / ``""`` 时抛 ValueError 让整次
    POST 500。这里把异常也收敛成 0，让 ``_read_json`` 后续 ``if length == 0``
    分支兜底。

    Args:
        raw: ``Content-Length`` 头的原始字符串值；``None`` 时也返回 0。

    Returns:
        非负整数；非法输入一律返回 0。
    """
    if not raw:
        return 0
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def start_server_background(loop: "ReActLoop") -> None:
    """后台起 HTTP 服务线程（token 鉴权 + 4 个 endpoint）。

    会把 ``loop.gate`` 的 channel 替换为 :func:`_http_approval_channel`
    （仅当 gate 是 :class:`HitlGate` 时），实现 HTTP 审批入站。

    Args:
        loop: 已启动的 :class:`ReActLoop`，用于替换 HITL channel 与保持引用。
    """
    s = get_settings()
    _loop_ref.append(loop)
    from .hitl.gate import HitlGate
    if isinstance(loop.gate, HitlGate):
        loop.gate.set_channel(_http_approval_channel)
    server = ThreadingHTTPServer((s.http_host, s.http_port), _make_handler(s.http_token))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()


def _decision_from_reply(reply: Any) -> Any:
    """把 HTTP /approve 端点 put 进 reply queue 的对象转成 :class:`ApprovalResult`。

    比 try/except 早一步拦截 ``reply`` 非 dict 的情况（攻击者塞 list/None
    等），避免把"网络超时"与"payload 格式错误"混为同一类失败。

    Args:
        reply: ``_http_reply_queue.get`` 取到的原始 JSON 解析结果（任意类型）。

    Returns:
        ``reply`` 为 dict 时按 ``decision`` / ``new_args`` / ``reason`` 字段
        构造 ``ApprovalResult``；非 dict 时返回 ``Decision.REJECT`` 并附
        ``reason='invalid reply payload'``。
    """
    from .hitl.gate import ApprovalResult, Decision
    if not isinstance(reply, dict):
        return ApprovalResult(decision=Decision.REJECT, reason="invalid reply payload")
    decision = Decision(reply.get("decision", "reject"))
    return ApprovalResult(
        decision=decision,
        edited_args=reply.get("new_args"),
        reason=reply.get("reason", ""),
    )


def _http_approval_channel(req: Any) -> Any:
    """HTTP 版的审批 channel：从 reply queue 取一次审批结果。

    超时 ``HTTP_REPLY_TIMEOUT_S`` 秒；任何异常都返回 REJECT 避免 Agent 卡死。

    Args:
        req: 审批请求对象；本 channel 不读其字段，仅用作 future 签名兼容。

    Returns:
        :class:`ApprovalResult`：成功时按 reply 内容构造，超时/异常时
        返回 ``Decision.REJECT`` 并附带 reason。
    """
    try:
        reply = _http_reply_queue.get(timeout=HTTP_REPLY_TIMEOUT_S)
        return _decision_from_reply(reply)
    except Exception as e:
        return ApprovalResult(decision=Decision.REJECT, reason=f"http channel error: {e}")


def _make_handler(token: str) -> type:
    """构造绑定 token 的 BaseHTTPRequestHandler 子类。

    路由：
        GET  /last-answer   → 返回最近一次 LLM answer
        GET  /health        → runtime_state (pid/heartbeat/restart_count)
        POST /message       → 塞进共享队列
        POST /approve       → 回复 HITL gate 一次

    Args:
        token: Bearer token；空串表示关闭鉴权（仅供本地 dev）。

    Returns:
        继承自 :class:`BaseHTTPRequestHandler` 的 handler 类，闭包里已绑定 token。
    """
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            """静默 BaseHTTPRequestHandler 默认访问日志（避免污染 stdout）。"""
            pass

        def _check_token(self) -> bool:
            """校验 Authorization 头是否匹配绑定 token；空 token 直接放行。"""
            if not token:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _auth_gate(self) -> bool:
            """统一 token 鉴权入口；未通过时已发 401，调用方直接 return。

            把 do_GET / do_POST 顶部重复的 4 行 token 检查 + 401 响应收敛到一处。

            Returns:
                True = 通过；False = 已发送 401 响应，调用方应直接 return。
            """
            if self._check_token():
                return True
            self._send_json(401, {"error": "unauthorized"})
            return False

        def _send_json(self, code: int, payload: dict) -> None:
            """把 payload 序列化为 JSON（UTF-8）并以 application/json 响应。

            Args:
                code: HTTP 状态码（200/401/404/503…）。
                payload: 可被 ``json.dumps`` 序列化的 dict；中文以 ``ensure_ascii=False`` 编码。
            """
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> "dict | None":
            """按 Content-Length 读取请求体并解析为 dict。

            Returns:
                解析后的 dict；body 为空或解析失败时返回 None。
            """
            length = _coerce_content_length(self.headers.get("Content-Length"))
            if length == 0:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return None

        def _dispatch(
            self,
            routes: "dict[str, Callable[[dict | None], None]]",
            body: "dict | None",
        ) -> None:
            """按 ``self.path`` 在 ``routes`` 表里查 handler；缺失返回 404。

            把 ``do_GET`` / ``do_POST`` 里重复的「if path == X: ...; 末尾 404
            收尾」收敛成 dispatch table；新增 endpoint 只需往 ``routes`` dict
            加一行，不用动方法分发逻辑。

            Args:
                routes: path → handler 映射；handler 签名统一为
                    ``(body: dict | None) -> None``，``do_GET`` 传 ``None``，
                    ``do_POST`` 传 ``_read_json() or {}``。
                body: 已解析的 POST body（GET 路径下为 ``None``）。
            """
            handler = routes.get(self.path)
            if handler is None:
                self._send_json(404, {"error": "not found"})
                return
            handler(body)

        # === handler methods（被 _dispatch 通过 routes dict 间接调用） ===

        def _handle_last_answer(self, _body: "dict | None") -> None:
            """``GET /last-answer``：返回最近一次 LLM answer。"""
            if _last_answer_box is None:
                self._send_json(503, {"error": "not ready"})
                return
            self._send_json(200, {"answer": _last_answer_box["answer"], "ts": _last_answer_box["ts"]})

        def _handle_health(self, _body: "dict | None") -> None:
            """``GET /health``：返回 runtime_state 健康快照（pid/heartbeat/restart_count）。

            从 do_GET 中抽出，让 do_GET 只剩路径分发。
            """
            import os
            from .watchdog import runtime_state as rs
            st = rs.read()
            self._send_json(200, {
                "ok": True, "pid": os.getpid(),
                "heartbeat_ts": st.get("heartbeat_ts"),
                "restart_count": st.get("restart_count", 0),
                "metamorphosis_pending": bool(st.get("metamorphosis_pending")),
            })

        def _handle_message(self, body: "dict") -> None:
            """``POST /message``：把父母消息塞进共享输入队列。

            空文本返 400；合法时回 200 + 文本预览。
            """
            text = _coerce_text(body.get("text"))
            if not text:
                self._send_json(400, {"error": "empty text"})
                return
            enqueue_message(text)
            self._send_json(200, {"ok": True, "queued": text[:_TEXT_PREVIEW_CHARS]})

        def _handle_approve(self, body: "dict") -> None:
            """``POST /approve``：把审批 payload put 进 reply queue 喂给 HITL gate。"""
            _http_reply_queue.put(body)
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            """处理 ``GET /last-answer`` 与 ``GET /health``；其他路径返回 404。"""
            if not self._auth_gate():
                return
            self._dispatch({
                "/last-answer": self._handle_last_answer,
                "/health":      self._handle_health,
            }, None)

        def do_POST(self) -> None:
            """处理 ``POST /message``（入队）与 ``POST /approve``（回复 HITL gate）；其他路径返回 404。"""
            if not self._auth_gate():
                return
            self._dispatch({
                "/message": self._handle_message,
                "/approve": self._handle_approve,
            }, self._read_json() or {})

    return Handler