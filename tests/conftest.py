"""pytest fixtures：临时仓库根 + clean settings cache。

每个测试都跑在自己的 tmp_path 下，避免污染真实 XRAgent 仓库。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from xragent.config import settings as settings_mod


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """构造临时仓库：含 .git/ + AGENTS.md + 子目录结构。"""
    # git init
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@xra"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), check=True)

    # AGENTS.md
    (tmp_path / "AGENTS.md").write_text("# TEST DREAM\n\ntest dream body", encoding="utf-8")
    # initial commit（让 HEAD 存在，metamorphosis 才有 base）
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)
    (tmp_path / "AGENTS.md").write_text("# TEST DREAM\n\ntest dream body", encoding="utf-8")

    # 子目录
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "diary").mkdir()
    (tmp_path / "diary" / "turns").mkdir()
    (tmp_path / "memory" / "long_term").mkdir(parents=True)
    (tmp_path / "evolve").mkdir()

    # 改 settings 让 repo_root 指向 tmp_path
    os.environ["XRAGENT_EVOLUTION_ENABLED"] = "true"
    os.environ["XRAGENT_LLM_PROVIDER"] = "mock"
    settings_mod.reset_settings_cache()

    s = settings_mod.get_settings()
    print(f"[conftest] before setattr: s.repo_root={s.repo_root}", flush=True)
    monkeypatch.setattr(s, "repo_root", tmp_path)
    print(f"[conftest] after setattr: s.repo_root={s.repo_root}", flush=True)
    print(f"[conftest] s._settings id={id(s)}", flush=True)
    monkeypatch.setattr(s, "memory_db", tmp_path / "memory" / "long_term" / "facts.db")
    monkeypatch.setattr(s, "diary_dir", tmp_path / "diary")
    monkeypatch.setattr(s, "turns_dir", tmp_path / "diary" / "turns")
    monkeypatch.setattr(s, "runtime_state_path", tmp_path / "runtime_state.json")
    monkeypatch.setattr(s, "generations_log", tmp_path / "evolve" / "generations.jsonl")
    monkeypatch.setattr(s, "http_port", 0)  # 测试时随机端口

    # dream cache 也清掉
    from xragent.core import dream as dream_mod
    dream_mod.load_dream.cache_clear()
    dream_mod.load_dream()
    # 重写 dream 的 repo_root 解析（用 settings.repo_root）
    # lru_cache 是基于路径的，settings.repo_root 改了之后它读到的是新路径
    yield tmp_path


# 暴露 XRAgent 仓库的 src/ 绝对路径，供需要 import xragent 的子进程用
XRAGENT_SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture
def xragent_src(monkeypatch: pytest.MonkeyPatch) -> Path:
    os.environ["XRAGENT_TEST_SRC"] = str(XRAGENT_SRC)
    return XRAGENT_SRC

    settings_mod.reset_settings_cache()
    dream_mod.load_dream.cache_clear()
