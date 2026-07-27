"""极简 HTTP 父母通道（可选）。"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from .config.settings import get_settings

if TYPE_CHECKING:
    from .core.react_loop import ReActLoop


_shared_queue: "queue.Queue[dict]" = queue.Queue()
_http_reply_queue: "queue.Queue[dict]" = queue.Queue()
_loop_ref: list = []


def enqueue_message(text: str) -> None:
    _shared_queue.put({"text": text})


def start_server_background(loop: "ReActLoop") -> None:
    s = get_settings()
    _loop_ref.append(loop)
    from .hitl.gate import HitlGate
    if isinstance(loop.gate, HitlGate):
        loop.gate.set_channel(_http_approval_channel)
    server = ThreadingHTTPServer((s.http_host, s.http_port), _make_handler(s.http_token))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()


def _http_approval_channel(req):
    from .hitl.gate import ApprovalResult, Decision
    try:
        reply = _http_reply_queue.get(timeout=120)
        decision = Decision(reply.get("decision", "reject"))
        return ApprovalResult(decision=decision, edited_args=reply.get("new_args"), reason=reply.get("reason", ""))
    except Exception as e:
        return ApprovalResult(decision=Decision.REJECT, reason=f"http channel error: {e}")


def _make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _check_token(self) -> bool:
            if not token:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _send_json(self, code: int, payload: dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict | None:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return None

        def do_GET(self):
            if not self._check_token():
                self._send_json(401, {"error": "unauthorized"})
                return
            if self.path == "/health":
                import os
                from .watchdog import runtime_state as rs
                st = rs.read()
                self._send_json(200, {
                    "ok": True, "pid": os.getpid(),
                    "heartbeat_ts": st.get("heartbeat_ts"),
                    "restart_count": st.get("restart_count", 0),
                    "metamorphosis_pending": bool(st.get("metamorphosis_pending")),
                })
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if not self._check_token():
                self._send_json(401, {"error": "unauthorized"})
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
