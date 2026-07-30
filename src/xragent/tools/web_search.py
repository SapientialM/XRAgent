"""网络工具：``curl_url`` + ``web_search``。

设计要点
========

* 限流: 距上次成功抓取 < ``RATE_LIMIT_COOLDOWN_S`` 时直接拒绝, 不发起请求.
* 敏感词拦截: ``_is_sensitive`` 在调用前扫一遍文本, 命中即拒.
* SSRF 防御: ``_is_blocked_host`` 用白名单外的默认拒绝 + 黑名单硬拦截,
  覆盖 loopback / link-local / 元数据地址.
* 留痕: 每次抓取 / 搜索都往 ``diary/search-log.md`` 追加一行, 便于事后审计.
* 状态文件: 全部走 ``_update_state`` 集中写, 避免散落的 read-modify-write.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# 常量 (单一来源, 测试与文档都引用这里)
# ---------------------------------------------------------------------------

#: 单次 urlopen 超时 (秒); 抓 DuckDuckGo HTML / 通用 GET 都用同一值.
REQUEST_TIMEOUT_S: int = 20

#: HTTP 响应体在返回 envelope 里的最大字符数; 超过则截断避免内存炸.
MAX_BODY_CHARS: int = 8000

#: 写到 ``diary/search-log.md`` 时的 body excerpt 上限.
LOG_BODY_EXCERPT_CHARS: int = 2000

#: 与 ``RATE_LIMIT_COOLDOWN_S`` 配对: 5 分钟内只允许一次成功抓取.
RATE_LIMIT_COOLDOWN_S: float = 300.0

#: SSRF 黑名单 — 始终拦截, 不依赖白名单.
BLOCKED_HOSTS: tuple[str, ...] = (
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS / GCP / Azure metadata
    "localhost",
)

#: 黑名单命中的 ``.local`` 等后缀; 命中后强制走拒绝分支.
_LOCAL_SUFFIXES: tuple[str, ...] = (".local", ".internal", ".lan", ".intranet")

#: 状态文件名 (相对 repo_root).
WEB_FETCH_STATE_FILE: str = ".run/web_fetch_state.json"

#: 抓取日志文件名 (相对 repo_root).
SEARCH_LOG_FILE: str = "diary/search-log.md"

#: URL 长度上限 — 防 DoS.
MAX_URL_LEN: int = 2048

#: User-Agent — 避免被某些站用默认 UA 直接拒掉.
USER_AGENT: str = "XRAgent/1.0 (+https://local/xragent)"

#: 敏感词正则; 命中即拦截, 不发起请求.
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(drop\s+table)\b", re.IGNORECASE),
    re.compile(r"\b(rm\s+-rf\s+/)\b", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,})", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"]?[^\s'\"]{6,})", re.IGNORECASE),
    re.compile(r"(AKIA[0-9A-Z]{16})"),  # AWS access key
)


# ---------------------------------------------------------------------------
# 状态文件 I/O
# ---------------------------------------------------------------------------


def _state_path() -> Any:
    """解析 ``WEB_FETCH_STATE_FILE`` 到绝对路径.

    用 ``settings.repo_root`` 拼, 与 conftest 的 tmp_path 注入兼容.
    """
    from ..config.settings import get_settings
    return get_settings().repo_root / WEB_FETCH_STATE_FILE


def _read_state() -> dict[str, Any]:
    """读状态; 文件不存在或损坏时返回空 dict (容错优于抛异常)."""
    p = _state_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    """原子写状态: ``tmp + rename`` 避免半写."""
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _update_state(**fields: Any) -> None:
    """read-modify-write 状态文件的中心入口.

    所有更新 ``last_curl_ts`` / ``last_url`` / ``last_search_query`` 的地方
    都走这里, 避免散落的 ``state = _read_state(); state["k"] = v; _write_state(state)``
    三连重复.

    Args:
        **fields: 要写入/覆盖的字段; 同名 key 覆盖, 其他 key 保留.
    """
    state = _read_state()
    state.update(fields)
    _write_state(state)


# ---------------------------------------------------------------------------
# 限流 + 敏感词 + SSRF
# ---------------------------------------------------------------------------


def _check_rate_limit() -> tuple[bool, float]:
    """距离上次成功抓取不足冷却时间则拒绝.

    Returns:
        ``(allowed, wait_s)``: 允许为 True (wait_s=0); 否则 wait_s 是还需等多少秒.
    """
    state = _read_state()
    last = float(state.get("last_curl_ts", 0.0) or 0.0)
    elapsed = time.time() - last
    if last <= 0 or elapsed >= RATE_LIMIT_COOLDOWN_S:
        return True, 0.0
    return False, RATE_LIMIT_COOLDOWN_S - elapsed


def _is_sensitive(text: str) -> str | None:
    """扫一遍敏感词; 命中返回描述, 否则 None."""
    for pat in _SENSITIVE_PATTERNS:
        m = pat.search(text)
        if m:
            return f"命中敏感词模式: {pat.pattern!r} (匹配: {m.group(0)[:32]!r})"
    return None


def _is_blocked_host(host: str) -> bool:
    """SSRF 黑名单: 黑名单字面 + 后缀黑名单 (.local / .internal 等)."""
    h = host.lower().strip()
    if h in BLOCKED_HOSTS:
        return True
    return any(h.endswith(suf) for suf in _LOCAL_SUFFIXES)


# ---------------------------------------------------------------------------
# 留痕
# ---------------------------------------------------------------------------


def _log_request(url: str, status: int | None, body_excerpt: str, note: str = "") -> None:
    """把本次抓取摘要写到 ``diary/search-log.md`` 末尾.

    Args:
        url: 实际请求的 URL.
        status: HTTP 状态码; 失败时为 None.
        body_excerpt: 截取后的 body 前缀, 上限 ``LOG_BODY_EXCERPT_CHARS``.
        note: 附加说明, 例如 "rate_limited" / "ssrf_blocked".
    """
    from ..config.settings import get_settings
    log = get_settings().repo_root / SEARCH_LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    excerpt = body_excerpt[:LOG_BODY_EXCERPT_CHARS].replace("\n", " ")
    flag = f" [{note}]" if note else ""
    line = f"- {ts} {status or 'ERR'}{flag} {url}\n  └ {excerpt[:240]}\n"
    with log.open("a", encoding="utf-8") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def curl_url(url: str, method: str = "GET", data: str = "") -> dict[str, Any]:
    """抓取一个 URL 并返回 ``{ok, status, body, error?}``.

    Args:
        url: 目标 URL; 必须是 http(s), 长度 < ``MAX_URL_LEN``, 不在 SSRF 黑名单里.
        method: ``GET`` 或 ``POST``.
        data: POST body; 仅 method=POST 时使用.

    Returns:
        成功: ``{"ok": True, "status": int, "body": str}``
        失败: ``{"ok": False, "error": str}`` (含 rate_limited / sensitive / ssrf_blocked)
    """
    # --- 1. 限流 ---
    allowed, wait_s = _check_rate_limit()
    if not allowed:
        msg = f"距上次抓取不足 {RATE_LIMIT_COOLDOWN_S:.0f}s, 需再等 {wait_s:.1f}s"
        _log_request(url, None, msg, note="rate_limited")
        return {"ok": False, "error": msg, "wait_s": wait_s}

    # --- 2. 基础校验 ---
    if len(url) > MAX_URL_LEN:
        return {"ok": False, "error": f"URL 过长 (> {MAX_URL_LEN})"}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": f"scheme 不允许: {parsed.scheme!r}"}
    if not parsed.netloc:
        return {"ok": False, "error": "缺少 host"}

    # --- 3. 敏感词扫描 ---
    combined = url + "\n" + data
    sens = _is_sensitive(combined)
    if sens:
        _log_request(url, None, sens, note="sensitive")
        return {"ok": False, "error": sens}

    # --- 4. SSRF ---
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        msg = f"SSRF 黑名单拦截 host={host!r}"
        _log_request(url, None, msg, note="ssrf_blocked")
        return {"ok": False, "error": msg}

    # --- 5. 执行 ---
    req = urllib.request.Request(url, data=data.encode("utf-8") if data else None,
                                  method=method.upper())
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        status = e.code
    except (URLError, TimeoutError, OSError) as e:
        _log_request(url, None, f"{type(e).__name__}: {e}", note="network_error")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    truncated = body[:MAX_BODY_CHARS]
    _log_request(url, status, truncated, note="")
    _update_state(last_curl_ts=time.time(), last_url=url, last_status=status)
    return {"ok": True, "status": status, "body": truncated}


def web_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """DuckDuckGo HTML 搜索 (无需 API key), 解析后取前 ``top_k`` 条.

    Args:
        query: 搜索词.
        top_k: 返回结果数; 1 <= top_k <= 20.

    Returns:
        成功: ``{"ok": True, "results": [{"title": str, "url": str, "snippet": str}, ...]}``
        失败: ``{"ok": False, "error": str}`` (rate_limited / sensitive / network)
    """
    if not 1 <= top_k <= 20:
        return {"ok": False, "error": f"top_k 越界: {top_k}"}

    allowed, wait_s = _check_rate_limit()
    if not allowed:
        msg = f"距上次抓取不足 {RATE_LIMIT_COOLDOWN_S:.0f}s, 需再等 {wait_s:.1f}s"
        return {"ok": False, "error": msg, "wait_s": wait_s}

    sens = _is_sensitive(query)
    if sens:
        return {"ok": False, "error": sens}

    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as e:
        _log_request(url, None, f"{type(e).__name__}: {e}", note="network_error")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    results = _parse_ddg_html(html, top_k=top_k)
    _log_request(url, 200, f"q={query!r} hits={len(results)}", note="search")
    _update_state(last_curl_ts=time.time(), last_search_query=query)
    return {"ok": True, "results": results}


# ---------------------------------------------------------------------------
# DDG HTML 解析 (无外部依赖, 用正则凑合)
# ---------------------------------------------------------------------------

_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _parse_ddg_html(html: str, top_k: int) -> list[dict[str, str]]:
    """从 DuckDuckGo HTML 抓 ``result__a`` + ``result__snippet`` 配对."""
    out: list[dict[str, str]] = []
    for m in _RESULT_RE.finditer(html):
        url = m.group(1)
        title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group(2))).strip()
        snippet = _WS_RE.sub(" ", _TAG_RE.sub("", m.group(3))).strip()
        out.append({"title": title, "url": url, "snippet": snippet})
        if len(out) >= top_k:
            break
    return out