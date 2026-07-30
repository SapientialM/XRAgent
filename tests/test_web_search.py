"""tests/test_web_search.py — 覆盖 web_search.py 的新常量 + helper.

只测纯逻辑 (state I/O / 限流 / SSRF / 敏感词); 网络抓取用 monkeypatch 跳过.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from xragent.tools import web_search


# ---------------------------------------------------------------------------
# _update_state — read-modify-write 中心
# ---------------------------------------------------------------------------


class TestUpdateState:
    """``_update_state`` 是本次 refactor 抽出的中心 helper."""

    def test_merges_new_fields(self, repo_root: Path) -> None:
        web_search._update_state(foo="bar", count=3)
        loaded = json.loads((repo_root / web_search.WEB_FETCH_STATE_FILE).read_text("utf-8"))
        assert loaded == {"foo": "bar", "count": 3}

    def test_preserves_existing_keys(self, repo_root: Path) -> None:
        web_search._update_state(first=1)
        web_search._update_state(second=2)
        loaded = json.loads((repo_root / web_search.WEB_FETCH_STATE_FILE).read_text("utf-8"))
        assert loaded == {"first": 1, "second": 2}

    def test_overwrites_same_key(self, repo_root: Path) -> None:
        web_search._update_state(k=1)
        web_search._update_state(k=2)
        loaded = json.loads((repo_root / web_search.WEB_FETCH_STATE_FILE).read_text("utf-8"))
        assert loaded["k"] == 2

    def test_no_fields_creates_empty_dict(self, repo_root: Path) -> None:
        web_search._update_state()
        loaded = json.loads((repo_root / web_search.WEB_FETCH_STATE_FILE).read_text("utf-8"))
        assert loaded == {}

    def test_unicode_roundtrip(self, repo_root: Path) -> None:
        web_search._update_state(中文="父母要求停下", emoji="🪴")
        loaded = json.loads((repo_root / web_search.WEB_FETCH_STATE_FILE).read_text("utf-8"))
        assert loaded["中文"] == "父母要求停下"
        assert loaded["emoji"] == "🪴"

    def test_atomic_write_no_leftover_tmp(self, repo_root: Path) -> None:
        web_search._update_state(a=1)
        tmp = (repo_root / web_search.WEB_FETCH_STATE_FILE).with_suffix(".json.tmp")
        assert not tmp.exists(), f"atomic 写入应清理 .tmp, 但 {tmp} 还在"


# ---------------------------------------------------------------------------
# 常量 — 单一来源, 测试防止被偷偷改坏
# ---------------------------------------------------------------------------


class TestConstants:
    def test_request_timeout_is_positive_int(self) -> None:
        assert isinstance(web_search.REQUEST_TIMEOUT_S, int)
        assert web_search.REQUEST_TIMEOUT_S > 0
        assert web_search.REQUEST_TIMEOUT_S <= 120, "URL 抓取不该等超过 2 分钟"

    def test_max_body_chars_positive(self) -> None:
        assert web_search.MAX_BODY_CHARS > 0
        assert web_search.MAX_BODY_CHARS <= 100_000

    def test_log_excerpt_smaller_than_max_body(self) -> None:
        assert web_search.LOG_BODY_EXCERPT_CHARS <= web_search.MAX_BODY_CHARS

    def test_rate_limit_cooldown_in_minutes_range(self) -> None:
        assert 60.0 <= web_search.RATE_LIMIT_COOLDOWN_S <= 600.0

    def test_blocked_hosts_covers_local_metadata(self) -> None:
        # 必须拦住这些 — 漏一个就是 SSRF 漏洞
        for host in ("127.0.0.1", "0.0.0.0", "169.254.169.254", "localhost"):
            assert host in web_search.BLOCKED_HOSTS, f"SSRF 黑名单漏了 {host}"

    def test_local_suffix_constants_exist(self) -> None:
        # .local / .internal / .lan / .intranet 是常见的 mDNS / 内网域名
        for suf in (".local", ".internal", ".lan", ".intranet"):
            assert suf in web_search._LOCAL_SUFFIXES


# ---------------------------------------------------------------------------
# SSRF 黑名单
# ---------------------------------------------------------------------------


class TestBlockedHost:
    @pytest.mark.parametrize("host", [
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",
        "localhost",
        "router.local",
        "printer.internal",
        "nas.lan",
        "wiki.intranet",
    ])
    def test_blocked(self, host: str) -> None:
        assert web_search._is_blocked_host(host) is True

    @pytest.mark.parametrize("host", [
        "example.com",
        "duckduckgo.com",
        "github.com",
        "192.168.1.1",  # 私网 RFC1918 — 这里仅做黑名单外验证, 不替代 _is_allowed_host
    ])
    def test_allowed(self, host: str) -> None:
        assert web_search._is_blocked_host(host) is False

    def test_case_insensitive(self) -> None:
        assert web_search._is_blocked_host("LOCALHOST") is True
        assert web_search._is_blocked_host("Router.LOCAL") is True


# ---------------------------------------------------------------------------
# 敏感词
# ---------------------------------------------------------------------------


class TestSensitive:
    @pytest.mark.parametrize("text", [
        "DROP TABLE users",
        "rm -rf /etc",
        "api_key=abcdefghijklmnop1234",
        'password="hunter2hunter"',
        "AKIAIOSFODNN7EXAMPLE",  # AWS key 文档里那个示例
    ])
    def test_caught(self, text: str) -> None:
        assert web_search._is_sensitive(text) is not None

    @pytest.mark.parametrize("text", [
        "hello world",
        "search for cute cats",
        "https://example.com/page",
        "drop the ball",  # "drop" 但不是 SQL 关键字
    ])
    def test_passed(self, text: str) -> None:
        assert web_search._is_sensitive(text) is None


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_first_call_allowed(self, repo_root: Path) -> None:
        allowed, wait = web_search._check_rate_limit()
        assert allowed is True
        assert wait == 0.0

    def test_within_cooldown_blocked(self, repo_root: Path) -> None:
        # 模拟"刚刚抓过" — last_curl_ts 设为 now
        web_search._update_state(last_curl_ts=__import__("time").time())
        allowed, wait = web_search._check_rate_limit()
        assert allowed is False
        assert 0 < wait <= web_search.RATE_LIMIT_COOLDOWN_S

    def test_old_timestamp_allowed(self, repo_root: Path) -> None:
        # 模拟"远古抓过" — last_curl_ts 设为 0
        web_search._update_state(last_curl_ts=0.0)
        allowed, _ = web_search._check_rate_limit()
        assert allowed is True

    def test_corrupt_state_file_is_recovered(self, repo_root: Path) -> None:
        # 状态文件被外部破坏 — 应容错而非崩
        p = repo_root / web_search.WEB_FETCH_STATE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json}", encoding="utf-8")
        state = web_search._read_state()
        assert state == {}
        # 接着写也能成功
        web_search._update_state(k="v")
        assert web_search._read_state() == {"k": "v"}


# ---------------------------------------------------------------------------
# curl_url — 不打网络, 只验前置校验
# ---------------------------------------------------------------------------


class TestCurlUrlGuards:
    """前置校验覆盖 (限流 / scheme / SSRF / 敏感词); 真发请求不在单元测试范围."""

    def test_blocked_host_short_circuits(self, repo_root: Path) -> None:
        # _check_rate_limit 通过 + 后续 SSRF 拦截
        r = web_search.curl_url("http://localhost/admin")
        assert r["ok"] is False
        assert "SSRF" in r["error"] or "黑名单" in r["error"]

    def test_metadata_ip_blocked(self, repo_root: Path) -> None:
        r = web_search.curl_url("http://169.254.169.254/latest/meta-data/")
        assert r["ok"] is False

    def test_invalid_scheme(self, repo_root: Path) -> None:
        r = web_search.curl_url("ftp://example.com/")
        assert r["ok"] is False
        assert "scheme" in r["error"]

    def test_url_too_long(self, repo_root: Path) -> None:
        long_url = "https://example.com/" + "a" * 5000
        r = web_search.curl_url(long_url)
        assert r["ok"] is False
        assert "过长" in r["error"]

    def test_missing_host(self, repo_root: Path) -> None:
        r = web_search.curl_url("https:///path")
        assert r["ok"] is False

    def test_sensitive_url_blocked(self, repo_root: Path) -> None:
        r = web_search.curl_url("https://example.com/?q=DROP TABLE users")
        assert r["ok"] is False
        assert "敏感词" in r["error"]

    def test_rate_limited_envelope_has_wait_s(self, repo_root: Path) -> None:
        web_search._update_state(last_curl_ts=__import__("time").time())
        r = web_search.curl_url("https://example.com/")
        assert r["ok"] is False
        assert "wait_s" in r
        assert r["wait_s"] > 0


# ---------------------------------------------------------------------------
# web_search — 不打网络, 只验前置校验
# ---------------------------------------------------------------------------


class TestWebSearchGuards:
    def test_top_k_out_of_range(self, repo_root: Path) -> None:
        assert web_search.web_search("foo", top_k=0)["ok"] is False
        assert web_search.web_search("foo", top_k=21)["ok"] is False

    def test_sensitive_query_blocked(self, repo_root: Path) -> None:
        r = web_search.web_search("DROP TABLE users")
        assert r["ok"] is False

    def test_rate_limited_envelope(self, repo_root: Path) -> None:
        web_search._update_state(last_curl_ts=__import__("time").time())
        r = web_search.web_search("hello")
        assert r["ok"] is False
        assert "wait_s" in r


# ---------------------------------------------------------------------------
# DDG HTML 解析 — 纯字符串处理
# ---------------------------------------------------------------------------


class TestDdgParse:
    """DDG HTML 解析是纯函数, 不打网络, 完全可测."""

    SAMPLE_HTML = """
    <html><body>
    <div class="result">
      <a class="result__a" href="https://example.com/a">Title A</a>
      <a class="result__snippet">Snippet A</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://example.com/b">Title B</a>
      <a class="result__snippet">Snippet B</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://example.com/c">Title C</a>
      <a class="result__snippet">Snippet C</a>
    </div>
    </body></html>
    """

    def test_top_k_truncates(self) -> None:
        out = web_search._parse_ddg_html(self.SAMPLE_HTML, top_k=2)
        assert len(out) == 2
        assert [r["url"] for r in out] == ["https://example.com/a", "https://example.com/b"]

    def test_default_top_k(self) -> None:
        out = web_search._parse_ddg_html(self.SAMPLE_HTML, top_k=5)
        assert len(out) == 3  # 实际只有 3 条

    def test_strips_tags(self) -> None:
        out = web_search._parse_ddg_html(self.SAMPLE_HTML, top_k=1)
        assert out[0]["title"] == "Title A"
        assert out[0]["snippet"] == "Snippet A"

    def test_empty_html_returns_empty(self) -> None:
        assert web_search._parse_ddg_html("", top_k=5) == []
        assert web_search._parse_ddg_html("<html>nothing</html>", top_k=5) == []


# ---------------------------------------------------------------------------
# 网络调用 mock — 验证 _update_state 被正确调用
# ---------------------------------------------------------------------------


class TestCurlUrlNetworkPath:
    """把 urlopen 替成 mock, 看 _update_state 是不是被正确触发."""

    def test_success_updates_state(self, repo_root: Path) -> None:
        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"hello world"

        with patch.object(web_search.urllib.request, "urlopen", return_value=FakeResp()):
            r = web_search.curl_url("https://example.com/")

        assert r == {"ok": True, "status": 200, "body": "hello world"}
        state = web_search._read_state()
        assert state["last_url"] == "https://example.com/"
        assert state["last_status"] == 200
        assert state["last_curl_ts"] > 0

    def test_http_error_returns_envelope(self, repo_root: Path) -> None:
        from urllib.error import HTTPError

        err = HTTPError(url="https://example.com/", code=404, msg="Not Found",
                        hdrs=None, fp=None)
        with patch.object(web_search.urllib.request, "urlopen", side_effect=err):
            r = web_search.curl_url("https://example.com/")
        # HTTPError 在本实现里被吞, 返回 ok=True + status=404 + 空 body
        assert r["ok"] is True
        assert r["status"] == 404

    def test_network_error_returns_error_envelope(self, repo_root: Path) -> None:
        from urllib.error import URLError
        with patch.object(web_search.urllib.request, "urlopen",
                          side_effect=URLError("boom")):
            r = web_search.curl_url("https://example.com/")
        assert r["ok"] is False
        assert "URLError" in r["error"]


class TestWebSearchNetworkPath:
    def test_success_returns_results(self, repo_root: Path) -> None:
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return TestDdgParse.SAMPLE_HTML.encode("utf-8")

        with patch.object(web_search.urllib.request, "urlopen", return_value=FakeResp()):
            r = web_search.web_search("cats", top_k=2)

        assert r["ok"] is True
        assert len(r["results"]) == 2
        # 状态被写入
        state = web_search._read_state()
        assert state["last_search_query"] == "cats"
        assert state["last_curl_ts"] > 0

    def test_network_error_returns_error(self, repo_root: Path) -> None:
        from urllib.error import URLError
        with patch.object(web_search.urllib.request, "urlopen",
                          side_effect=URLError("dns")):
            r = web_search.web_search("cats")
        assert r["ok"] is False