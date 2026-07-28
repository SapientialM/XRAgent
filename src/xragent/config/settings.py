"""xragent 配置中心。

所有可调参数走 pydantic-settings；环境变量优先级 > .env > 默认值。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 仓库根 = 本文件向上 3 级（src/xragent/config/settings.py -> xragent/config -> xragent -> repo root）
REPO_ROOT: Path = Path(__file__).resolve().parents[3]


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
    cmd_blacklist: tuple[str, ...] = ("curl", "wget", "ssh", "scp", "nc", "ncat")

    # === 工具黑名单路径（仓库内相对路径 resolve 后） ===
    write_blacklist: tuple[str, ...] = (
        "AGENTS.md",  # 梦想：Agent 不可改
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

    # === derivation ===
    @property
    def active_api_key(self) -> str:
        return {
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "glm": self.glm_api_key,
            "minimaxi": self.minimaxi_api_key,
        }.get(self.llm_provider, "")

    @property
    def active_base_url(self) -> str:
        return {
            "openai": self.openai_base_url,
            "deepseek": self.deepseek_base_url,
            "glm": self.glm_base_url,
            "minimaxi": self.minimaxi_base_url,
        }.get(self.llm_provider, "")

    @property
    def active_model(self) -> str:
        """不同 provider 有独立 model 字段；统一从这里取。"""
        if self.llm_provider == "minimaxi" and self.minimaxi_model:
            return self.minimaxi_model
        return self.llm_model

    @model_validator(mode="before")
    @classmethod
    def _backfill_jacecli_env(cls, values):
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
    global _settings
    _settings = None
