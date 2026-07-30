"""极简 HTTP 父母通道（可选）。"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

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


def register_input_queue(q: "queue.Queue") -> None:
    """main.py 注册共享输入队列；HTTP /message 直接 put。"""
    global _shared_input_queue
    _shared_input_queue = q


def register_answer_sink(box: dict) -> None:
    """main.py 注册 last_answer 容器；HTTP /last-answer 读它。"""
    global _last_answer_box
    _last_answer_box = box


def enqueue_message(text: str) -> None:
    """把人类父母消息塞进共享输入队列。

    Raises:
        RuntimeError: 共享队列还没注册（main.py 没启动）。
    """
    if _shared_input_queue is not None:
        _shared_input_queue.put(text)
    else:
        raise RuntimeError("input queue 未注册；用 xragent.main --serve 启动")


def start_server_background(loop: "ReActLoop") -> None:
    """后台起 HTTP 服务线程（token 鉴权 + 4 个 endpoint）。

    会替换 loop.gate 的 channel 为 HTTP 实现。
    """
    s = get_settings()
    _loop_ref.append(loop)
    from .hitl.gate import HitlGate
    if isinstance(loop.gate, HitlGate):
        loop.gate.set_channel(_http_approval_channel)
    server = ThreadingHTTPServer((s.http_host, s.http_port), _make_handler(s.http_token))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()


def _http_approval_channel(req: Any) -> Any:
    """HTTP 版的审批 channel：从 reply queue 取一次审批结果。

    超时 ``HTTP_REPLY_TIMEOUT_S`` 秒；任何异常都返回 REJECT 避免 Agent 卡死。
    """
    from .hitl.gate import ApprovalResult, Decision
    try:
        reply = _http_reply_queue.get(timeout=HTTP_REPLY_TIMEOUT_S)
        decision = Decision(reply.get("decision", "reject"))
        return ApprovalResult(decision=decision, edited_args=reply.get("new_args"), reason=reply.get("reason", ""))
    except Exception as e:
        return ApprovalResult(decision=Decision.REJECT, reason=f"http channel error: {e}")


def _make_handler(token: str) -> type:
    """构造绑定 token 的 BaseHTTPRequestHandler 子类。

    路由：
        GET  /last-answer   → 返回最近一次 LLM answer
        GET  /health        → runtime_state (pid/heartbeat/restart_count)
        POST /message       → 塞进共享队列
        POST /approve       → 回复 HITL gate 一次
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
            """把 payload 序列化为 JSON（UTF-8）并以 application/json 响应。"""
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
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return None

        def _handle_health(self) -> None:
            """GET /health：返回 runtime_state 健康快照（pid/heartbeat/restart_count）。

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

        def do_GET(self) -> None:
            """处理 GET /last-answer 与 GET /health；其他路径返回 404。"""
            if not self._auth_gate():
                return
            if self.path == "/last-answer":
                if _last_answer_box is None:
                    self._send_json(503, {"error": "not ready"})
                    return
                self._send_json(200, {"answer": _last_answer_box["answer"], "ts": _last_answer_box["ts"]})
                return
            if self.path == "/health":
                self._handle_health()
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            """处理 POST /message（入队）与 POST /approve（回复 HITL gate）；其他路径返回 404。"""
            if not self._auth_gate():
                return
            body = self._read_json() or {}
            if self.path == "/message":
                text = (body.get("text") or "").strip()
                if not text:
                    self._send_json(400, {"error": "empty text"})
                    return
                enqueue_message(text)
                self._send_json(200, {"ok": True, "queued": text[:80]})
                return
            if self.path == "/approve":
                _http_reply_queue.put(body)
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

    return Handler