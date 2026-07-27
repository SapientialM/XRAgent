"""xragent 配置中心。"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT: Path = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_prefix="XRAGENT_",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: Literal["openai", "deepseek", "glm", "mock"] = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    hitl_default: Literal["interactive", "approve-all", "reject-all"] = "interactive"
    http_token: str = ""
    http_host: str = "127.0.0.1"
    http_port: int = 10086

    evolution_enabled: bool = True

    heartbeat_interval_s: int = 10
    heartbeat_timeout_s: int = 60
    restart_max_failures: int = 5

    repo_root: Path = Field(default_factory=lambda: REPO_ROOT)
    memory_db: Path = Field(default_factory=lambda: REPO_ROOT / "memory" / "long_term" / "facts.db")
    diary_dir: Path = Field(default_factory=lambda: REPO_ROOT / "diary")
    turns_dir: Path = Field(default_factory=lambda: REPO_ROOT / "diary" / "turns")
    runtime_state_path: Path = Field(default_factory=lambda: REPO_ROOT / "runtime_state.json")
    generations_log: Path = Field(default_factory=lambda: REPO_ROOT / "evolve" / "generations.jsonl")

    context_budget_tokens: int = 20_000
    compress_target_ratio: float = 0.7

    cmd_blacklist: tuple[str, ...] = ("curl", "wget", "ssh", "scp", "nc", "ncat")

    write_blacklist: tuple[str, ...] = (
        "AGENTS.md",
        ".env",
        ".git",
        "runtime_state.json",
        "diary/turns",
    )

    # SideGit stash 时排除的路径（避免误清源代码）
    stash_excludes: tuple[str, ...] = (
        "src/",
        "tests/",
        "docs/",
        "AGENTS.md",
        "pyproject.toml",
        ".env.example",
        ".gitignore",
    )

    @property
    def active_api_key(self) -> str:
        return {
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "glm": self.glm_api_key,
        }.get(self.llm_provider, "")

    @property
    def active_base_url(self) -> str:
        return {
            "openai": self.openai_base_url,
            "deepseek": self.deepseek_base_url,
            "glm": self.glm_base_url,
        }.get(self.llm_provider, "")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    global _settings
    _settings = None
