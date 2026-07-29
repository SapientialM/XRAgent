"""Web 搜索 / URL 抓取（带留痕 + 敏感词拦截）。

- 把 curl 能力开放给 Agent，但强制走这个 wrapper
- 所有请求写 diary/search-log.md（让父母/审计能看到 Agent 查了什么）
- 拒绝包含敏感词的 URL/query
"""
from __future__ import annotations

import time
import urllib.request
import urllib.parse
from typing import Any

from ..config.settings import get_settings


# 敏感词（不区分大小写）：URL 包含这些词就拒绝执行
SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "apikey",
    "api_key",
    "api-key",
    "sk-",          # OpenAI / MiniMax key 前缀
    "bearer ",
    "credential",
    "private_key",
    "access_token",
    "aws_secret",
)


def _is_sensitive(text: str) -> str | None:
    """返回命中的敏感词（首个小写），没有则 None。"""
    low = text.lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in low:
            return kw
    return None


def _log_request(url: str, status: int | None, body_excerpt: str, note: str = "") -> None:
    s = get_settings()
    log = s.repo_root / "diary" / "search-log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n## {ts}\n")
        if note:
            f.write(f"note: {note}\n")
        f.write(f"url: {url}\n")
        if status is not None:
            f.write(f"status: {status}\n")
        f.write(f"body_excerpt:\n\`\`\`\n{body_excerpt[:2000]}\n\`\`\`\n---\n")


def curl_url(url: str, method: str = "GET", data: str = "") -> dict[str, Any]:
    """抓取 URL 内容（最多 8000 字符）；自动写 diary/search-log.md。

    Parameters
    ----------
    url : str
        完整 URL（含 http:// 或 https://）
    method : str
        GET / POST
    data : str
        POST body（GET 时忽略）

    Returns
    -------
    dict
        ok / status / body / error
    """
    s = get_settings()

    # 1) 敏感词拦截
    hit = _is_sensitive(url)
    if hit:
        _log_request(url, None, f"BLOCKED: sensitive keyword \'{hit}\'", note="BLOCKED")
        return {"ok": False, "error": f"敏感词被拦截: {hit!r}（改用更抽象的 query）"}

    # 2) 必须 http(s)
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": f"URL 必须以 http:// 或 https:// 开头：{url[:60]}"}

    # 3) 限制 host（白名单）— 防止 SSRF
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in ("127.0.0.1", "0.0.0.0", "169.254.169.254") or host.endswith(".local") or host == "localhost":
        return {"ok": False, "error": f"host {host} 被拦截（SSRF 防护）"}

    # 4) 执行
    headers = {"User-Agent": "XRAgent/0.1 (research bot; logs to diary/search-log.md)"}
    body_bytes: bytes | None = None
    try:
        if method.upper() == "POST" and data:
            req = urllib.request.Request(url, data=data.encode("utf-8"), headers=headers, method="POST")
        else:
            req = urllib.request.Request(url, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
            body_bytes = r.read()
    except Exception as e:
        _log_request(url, None, f"ERR: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    body = body_bytes.decode("utf-8", errors="replace")[:8000] if body_bytes else ""
    _log_request(url, status, body, note=f"method={method}")
    return {"ok": True, "status": status, "body": body, "url": url}


def web_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """用 DuckDuckGo HTML 抓取搜索结果（无需 API key）。

    Returns: ok / results: [{title, url, snippet}]
    """
    s = get_settings()
    hit = _is_sensitive(query)
    if hit:
        _log_request(f"search://{query}", None, f"BLOCKED: sensitive keyword \'{hit}\'", note="SEARCH-BLOCKED")
        return {"ok": False, "error": f"敏感词被拦截: {hit!r}"}

    ddg_url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    headers = {"User-Agent": "Mozilla/5.0 (XRAgent research bot)"}
    try:
        req = urllib.request.Request(ddg_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    import re
    results = []
    for m in re.finditer(r'''<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>''', body, re.DOTALL):
        url = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not url.startswith("http"):
            continue
        if _is_sensitive(url):
            continue
        results.append({"title": title, "url": url})
        if len(results) >= top_k:
            break

    _log_request(ddg_url, 200, f"search={query!r} results={len(results)}", note="SEARCH")
    return {"ok": True, "query": query, "results": results}
