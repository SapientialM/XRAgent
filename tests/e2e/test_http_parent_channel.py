"""e2e #4：HTTP 父母通道端到端 — POST /message → Agent 处理 → GET /last-answer。

启动 xragent.main --serve 在后台；通过 HTTP 喂消息；验证 last-answer 被更新。
本机直连（127.0.0.1），绕过 urllib 的系统代理检测。
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _LocalResp:
    """http.client 响应的 file-like 包装。"""
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body
    def read(self) -> bytes:
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


def _do_request(host: str, port: int, method: str, path: str,
                body: bytes | None = None, headers: dict | None = None,
                timeout: float = 5.0) -> _LocalResp:
    """直接走 http.client，绕过 urllib 代理。"""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return _LocalResp(resp.status, resp.read())
    finally:
        conn.close()


def test_http_message_round_trip(repo_root, xragent_src, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("XRAGENT_HTTP_PORT", str(port))
    monkeypatch.setenv("XRAGENT_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("XRAGENT_LLM_PROVIDER", "mock")
    monkeypatch.setenv("XRAGENT_TEST_REPO", str(repo_root))
    from xragent.config import settings as sm
    sm.reset_settings_cache()

    env = os.environ.copy()
    env["XRAGENT_TEST_SRC"] = str(xragent_src)
    env["XRAGENT_TEST_REPO"] = str(repo_root)
    env["XRAGENT_HTTP_PORT"] = str(port)
    env["XRAGENT_LLM_PROVIDER"] = "mock"
    env["PYTHONPATH"] = str(xragent_src)

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "xragent.main", "--serve"],
        cwd=str(repo_root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        # 等 HTTP server 起来
        server_ready = False
        for _ in range(30):
            time.sleep(0.3)
            try:
                r = _do_request("127.0.0.1", port, "GET", "/health", timeout=2)
                if r.status == 200:
                    server_ready = True
                    break
            except Exception:
                continue
        if not server_ready:
            out, _ = proc.communicate(timeout=3)
            pytest.fail(f"HTTP server 未起来.\nsubprocess output:\n{out}")

        # POST /message
        r = _do_request(
            "127.0.0.1", port, "POST", "/message",
            body=json.dumps({"text": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        assert r.status == 200
        body = json.loads(r.read().decode("utf-8"))
        assert body["ok"] is True

        # 等处理；GET /last-answer
        answer = ""
        for _ in range(20):
            time.sleep(0.3)
            r = _do_request("127.0.0.1", port, "GET", "/last-answer", timeout=2)
            body = json.loads(r.read().decode("utf-8"))
            if body.get("answer"):
                answer = body["answer"]
                break
        assert answer, "last-answer 始终为空"
        assert "XRAgent" in answer or "息壤" in answer
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
