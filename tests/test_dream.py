"""梦想加载器 + 路径保护判定。"""
from __future__ import annotations

from xragent.core.dream import (
    assemble_system_prompt,
    is_protected,
    load_dream,
    safety_reminder,
)


def test_load_dream_reads_agents_md(repo_root):
    assert "test dream body" in load_dream()


def test_assemble_system_prompt_has_dream_and_safety(repo_root):
    sp = assemble_system_prompt()
    assert "[DREAM" in sp and "[/DREAM]" in sp
    assert "[SAFETY REMINDER]" in sp and "[/SAFETY REMINDER]" in sp
    assert "test dream body" in sp


def test_is_protected_blocks_dream_and_turns(repo_root):
    assert is_protected(repo_root / "AGENTS.md") is True
    assert is_protected(repo_root / "diary" / "turns" / "x.jsonl") is True
    assert is_protected(repo_root / ".env") is True


def test_is_protected_allows_normal(repo_root):
    assert is_protected(repo_root / "sandbox" / "x.py") is False


def test_is_protected_blocks_outside_repo():
    assert is_protected("/etc/passwd") is True


def test_safety_reminder_mentions_terminate():
    s = safety_reminder()
    assert "terminate" in s.lower()
