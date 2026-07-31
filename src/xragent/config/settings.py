"""xragent 配置中心。

所有可调参数走 pydantic-settings；环境变量优先级 > .env > 默认值。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 仓库根 = 本文件向上 3 级（src/xragent/config/settings.py -> xragent/config -> xragent -> repo root）
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

# 当前 Settings 上"按 provider 命名前缀"的字段集；用于 _provider_attr 统一查找。
# 新增 provider 时只需：1) 加进 llm_provider Literal；2) 在此声明对应 {provider}_api_key /
# {provider}_base_url 字段。_provider_attr 不需改。
_PROVIDERS_WITH_API: tuple[str, ...] = ("openai", "deepseek", "glm", "minimaxi")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_prefix="XRAGENT_",
        extra="ignore",
        case_sensitive=False,
    )

    # === LLM ===
    llm_provider: Literal[
        "openai", "deepseek", "glm",
        "minimaxi", "minimax", "minimax-ai", "minimax_ai",
        "mock",
    ] = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    # MiniMax（注意官方拼写：minimaxi，不是 minimax；alias 兼容 minimax/minimax-ai）
    minimaxi_api_key: str = ""
    minimaxi_base_url: str = "https://api.minimaxi.com/v1"
    minimaxi_model: str = "MiniMax-M3"

    # === 五核心 · 父母通道 ===
    hitl_default: Literal["interactive", "approve-all", "reject-all"] = "interactive"
    http_token: str = ""
    http_host: str = "127.0.0.1"
    http_port: int = 10086

    # === 五核心 · 成长开关 ===
    evolution_enabled: bool = True

    # === Push cadence（autonomous 模式每 N 分钟批量 push 一次，避免每次 commit 都 push） ===
    push_interval_minutes: int = 30

    # === Watchdog ===
    heartbeat_interval_s: int = 10
    heartbeat_timeout_s: int = 60
    restart_max_failures: int = 5

    # === 路径 ===
    repo_root: Path = Field(default_factory=lambda: REPO_ROOT)
    memory_db: Path = Field(default_factory=lambda: REPO_ROOT / "memory" / "long_term" / "facts.db")
    diary_dir: Path = Field(default_factory=lambda: REPO_ROOT / "diary")
    turns_dir: Path = Field(default_factory=lambda: REPO_ROOT / "diary" / "turns")
    runtime_state_path: Path = Field(default_factory=lambda: REPO_ROOT / "runtime_state.json")
    generations_log: Path = Field(default_factory=lambda: REPO_ROOT / "evolve" / "generations.jsonl")

    # === 上下文预算 ===
    context_budget_tokens: int = 20_000
    compress_target_ratio: float = 0.7

    # === run_cmd 黑名单 binary ===
    cmd_blacklist: tuple[str, ...] = ("wget", "ssh", "scp", "nc", "ncat")  # curl 已开放给 web_search 工具（带限流）

    # === run_cmd 黑名单 regex patterns（用户自定义）===
    # 与 ``cmd_blacklist``（binary 精确名）互补：本字段是 regex 列表，对 *整条 cmd*
    # 走 ``re.search`` 匹配，命中即拦。允许通过 XRAGENT_CMD_BLACKLIST_PATTERNS 环境
    # 变量（JSON 数组字符串）注入。
    # 示例：["^\\s*rm\\b", "iptables\\s+.*flush", "mkfs\\."]
    cmd_blacklist_patterns: tuple[str, ...] = ()

    # === 工具黑名单路径（仓库内相对路径 resolve 后） ===
    write_blacklist: tuple[str, ...] = (
        ".env",
        ".git",
        "runtime_state.json",
        "diary/turns",  # 结构化日志：Agent 不可自我粉饰
    )

    # === SideGit stash 排除（避免误清源代码） ===
    stash_excludes: tuple[str, ...] = (
        "src/",
        "tests/",
        "docs/",
        "AGENTS.md",
        "pyproject.toml",
        ".env.example",
        ".gitignore",
    )

    # === SideGit snapshot 清理阈值（cleanup_old_snapshots 用）===
    # 0 / 负数 = 禁用清理；默认保留 30 天内的 xragent/turn-* tag。
    # 用户手工打的 v0.1 / baseline 等里程碑 tag 不在此列,只清理自动前缀。
    snapshot_retention_days: int = 30

    # === derivation ===
    def _provider_attr(self, suffix: str) -> str:
        """按 ``llm_provider`` 在 Settings 上查找 ``{provider}_{suffix}`` 字段值。

        例如 ``_provider_attr("api_key")`` 在 ``llm_provider="openai"`` 时返回
        ``self.openai_api_key``。provider 不在白名单（如 ``mock``/未声明的
        alias）或对应字段不存在时返回 ``""``，与原 dict-literal ``.get(..., "")``
        兜底一致。
        """
        if self.llm_provider not in _PROVIDERS_WITH_API:
            return ""
        attr = f"{self.llm_provider}_{suffix}"
        return getattr(self, attr, "")

    @property
    def active_api_key(self) -> str:
        """当前 ``llm_provider`` 对应的 API key；走 ``_provider_attr`` 转发。

        provider 不在白名单（如 ``mock``/alias）时返回 ``""``，调用方需自行判空。
        """
        return self._provider_attr("api_key")

    @property
    def active_base_url(self) -> str:
        """当前 ``llm_provider`` 对应的 base URL；走 ``_provider_attr`` 转发。

        provider 不在白名单时返回 ``""``；调用方拿到 ``""`` 应回退到 SDK 默认
        或报错，不要凭默认 base 假装可用。
        """
        return self._provider_attr("base_url")

    @property
    def active_model(self) -> str:
        """不同 provider 有独立 model 字段；统一从这里取。"""
        if self.llm_provider == "minimaxi" and self.minimaxi_model:
            return self.minimaxi_model
        return self.llm_model

    @model_validator(mode="before")
    @classmethod
    def _backfill_jacecli_env(cls, values: Any) -> Any:
        """兼容 JaceCLI 风格 env var（无 XRAGENT_ 前缀）。

        如果 pydantic-settings 没从 XRAGENT_MINIMAXI_API_KEY 读到 key，
        尝试从 MINIMAXI_API_KEY / MINIMAXI_BASE_URL / MINIMAXI_MODEL 读。
        当两者都设时，XRAGENT_ 风格优先（先 populate）。
        """
        import os
        if not isinstance(values, dict):
            return values
        if not values.get("minimaxi_api_key"):
            v = os.environ.get("MINIMAXI_API_KEY", "")
            if v:
                values["minimaxi_api_key"] = v
        if values.get("minimaxi_base_url", "https://api.minimaxi.com/v1") == "https://api.minimaxi.com/v1":
            v = os.environ.get("MINIMAXI_BASE_URL", "")
            if v:
                values["minimaxi_base_url"] = v
        if not values.get("minimaxi_model"):
            v = os.environ.get("MINIMAXI_MODEL", "")
            if v:
                values["minimaxi_model"] = v
        return values


_settings: Settings | None = None


def get_settings() -> Settings:
    """延迟初始化；可被测试 monkeypatch。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """重置 ``get_settings`` 的进程内缓存；测试/配置热加载时调用。"""
    global _settings
    _settings = None