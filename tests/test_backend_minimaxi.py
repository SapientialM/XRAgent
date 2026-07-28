"""MiniMax provider 适配测试。

不实际发请求（避免消耗 token）；只验证：
- env var 路径（XRAGENT_MINIMAXI_API_KEY 与 JaceCLI 风格 MINIMAXI_API_KEY）
- alias（minimax / minimax-ai → minimaxi）
- get_backend() 返回 LangChainBackend（如果 api_key 存在）
"""
from __future__ import annotations

import pytest


def test_minimaxi_env_loaded_xragent_style(monkeypatch):
    """XRAGENT_MINIMAXI_API_KEY 风格。"""
    monkeypatch.setenv("XRAGENT_LLM_PROVIDER", "minimaxi")
    monkeypatch.setenv("XRAGENT_MINIMAXI_API_KEY", "sk-xragent-test")
    monkeypatch.setenv("XRAGENT_MINIMAXI_BASE_URL", "https://api.minimaxi.com/v1")

    from xragent.config import settings as sm
    sm.reset_settings_cache()
    s = sm.get_settings()
    assert s.minimaxi_api_key == "sk-xragent-test"
    assert s.active_api_key == "sk-xragent-test"
    assert s.active_base_url == "https://api.minimaxi.com/v1"
    assert s.active_model == "MiniMax-M3"


def test_minimaxi_env_loaded_jacecli_style(monkeypatch):
    """JaceCLI 风格 MINIMAXI_API_KEY（无 XRAGENT_ 前缀）。"""
    monkeypatch.delenv("XRAGENT_MINIMAXI_API_KEY", raising=False)
    monkeypatch.setenv("XRAGENT_LLM_PROVIDER", "minimaxi")
    monkeypatch.setenv("MINIMAXI_API_KEY", "sk-jacecli-style")
    monkeypatch.setenv("MINIMAXI_BASE_URL", "https://api.minimaxi.com/v1")

    from xragent.config import settings as sm
    sm.reset_settings_cache()
    s = sm.get_settings()
    assert s.minimaxi_api_key == "sk-jacecli-style"
    assert s.active_api_key == "sk-jacecli-style"


def test_minimaxi_xragent_takes_precedence_over_jacecli(monkeypatch):
    """两者都设时 XRAGENT_ 风格优先。"""
    monkeypatch.setenv("XRAGENT_MINIMAXI_API_KEY", "sk-xragent")
    monkeypatch.setenv("MINIMAXI_API_KEY", "sk-jacecli")

    from xragent.config import settings as sm
    sm.reset_settings_cache()
    s = sm.get_settings()
    assert s.minimaxi_api_key == "sk-xragent"


def test_minimaxi_alias_normalized(monkeypatch):
    """minimax / minimax-ai / minimax_ai alias 都解析到 minimaxi。"""
    from xragent.core.backend import _normalize_provider
    assert _normalize_provider("minimaxi") == "minimaxi"
    assert _normalize_provider("minimax") == "minimaxi"
    assert _normalize_provider("minimax-ai") == "minimaxi"
    assert _normalize_provider("minimax_ai") == "minimaxi"
    assert _normalize_provider("openai") == "openai"


def test_minimaxi_literal_accepts_alias():
    """pydantic Literal 接受 alias 字符串。"""
    from xragent.config.settings import Settings
    # 应该不抛 ValidationError
    for alias in ("minimaxi", "minimax", "minimax-ai", "minimax_ai"):
        Settings(llm_provider=alias)


def test_get_backend_with_minimaxi(monkeypatch):
    """minimaxi + key 存在时返回 LangChainBackend（不实际发请求）。"""
    monkeypatch.setenv("XRAGENT_LLM_PROVIDER", "minimaxi")
    monkeypatch.setenv("XRAGENT_MINIMAXI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("XRAGENT_MINIMAXI_BASE_URL", "https://api.minimaxi.com/v1")

    from xragent.config import settings as sm
    sm.reset_settings_cache()
    from xragent.core.backend import get_backend
    backend = get_backend()
    assert type(backend).__name__ == "LangChainBackend"
    assert backend.settings.active_model == "MiniMax-M3"
    assert backend.settings.active_base_url == "https://api.minimaxi.com/v1"


def test_get_backend_falls_back_to_mock_without_key(monkeypatch):
    """minimaxi + 无 key 时回退到 MockBackend。"""
    monkeypatch.setenv("XRAGENT_LLM_PROVIDER", "minimaxi")
    monkeypatch.delenv("XRAGENT_MINIMAXI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAXI_API_KEY", raising=False)

    from xragent.config import settings as sm
    sm.reset_settings_cache()
    from xragent.core.backend import get_backend
    backend = get_backend()
    assert type(backend).__name__ == "MockBackend"
