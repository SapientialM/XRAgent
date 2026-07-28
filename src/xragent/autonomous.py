"""自驱动循环：无人值守时按 task templates 循环推进。

不是 AGI，是「按一份多元化任务清单 + ReAct 循环 + commit」，
让它在没人在的时候也能稳定推进：加测试 / 改文档 / 重构 / 优化 prompt。
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Iterator

from .config.settings import get_settings


# 任务模板：覆盖测试 / 文档 / 重构 / prompt / 自我观察
TASK_TEMPLATES = [
    {
        "title": "审视代码",
        "prompt": (
            "读 src/xragent/ 下任一模块的源代码，找出一个能改进的点"
            "（性能 / 可读性 / 边界条件处理 / 测试覆盖）。改完后跑 `scripts/test` 验证。"
            "如果跑测试失败，回滚改动并换下一个改进点。"
        ),
    },
    {
        "title": "补充测试",
        "prompt": (
            "为 src/xragent/ 下某个工具/模块增加单元测试覆盖之前没测过的边界条件。"
            "新测试加到 tests/test_*.py 末尾，跑 `scripts/test` 确认全部通过。"
        ),
    },
    {
        "title": "更新文档",
        "prompt": (
            "阅读 README.md + docs/architecture-v0.md + AGENTS.md，找一个没说清楚或过时的地方，"
            "补一段说明。保持简洁——三句话能说清就别写十句。"
        ),
    },
    {
        "title": "反思日记",
        "prompt": (
            "读 diary/2026-07-28.md + runtime_state.json 状态，写一段"
            "对自己当前能力的客观评估（哪里做得好、哪里有缺陷），存入 memory/long_term/facts.db。"
            "category 字段填 'self_reflection'。"
        ),
    },
    {
        "title": "优化提示词",
        "prompt": (
            "审视 src/xragent/core/dream.py 的 system_prompt_prefix 与 safety_reminder，"
            "看是否有冗余、歧义或可改进的措辞。改完后跑 smoke 测试 (`scripts/smoke`) 验证。"
        ),
    },
    {
        "title": "改进 memory",
        "prompt": (
            "读 src/xragent/memory/manager.py，看 SQLite schema 是否有可优化的索引"
            "或缺失字段。改完后跑单测 `PYTHONPATH=src python3.11 -m pytest tests/test_memory.py -v`。"
        ),
    },
    {
        "title": "改善工具",
        "prompt": (
            "读 src/xragent/tools/ 下某个工具的实现，看是否有更 Pythonic 的写法或更好的错误处理。"
            "改完后跑 `scripts/test`。如果改动导致某个工具行为变了，明确写出来。"
        ),
    },
    {
        "title": "金蝉脱壳演练",
        "prompt": (
            "运行一次完整金蝉脱壳演练：commit 当前所有改动 → push → py_compile 验证 → 写世代谱。"
            "如发现编译失败，立刻 `git revert HEAD` 回滚并把错误写进 diary。"
        ),
    },
]


def task_queue_path() -> Path:
    """Agent 自己的任务队列（不入 git）。"""
    s = get_settings()
    return s.repo_root / "memory" / "queue.jsonl"


def task_cooldown_key(task: dict) -> str:
    return task["title"]


def _recent_titles(window_s: float = 3600.0) -> set[str]:
    """返回最近 window_s 秒内做过的任务 title 集合（用于 cooldown）。"""
    p = task_queue_path()
    if not p.exists():
        return set()
    cutoff = time.time() - window_s
    seen: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("ts", 0) >= cutoff:
                seen.add(rec.get("title", ""))
        except json.JSONDecodeError:
            continue
    return seen


def next_task(rng: random.Random | None = None) -> dict:
    """从 templates 选一个不在 cooldown 里的任务。

    cooldown：同 title 1 小时内不重复。
    全冷却时返回第一个（让 Agent 自己想办法或蜕皮）。
    """
    rng = rng or random
    recent = _recent_titles()
    candidates = [t for t in TASK_TEMPLATES if task_cooldown_key(t) not in recent]
    if not candidates:
        return TASK_TEMPLATES[0]
    return rng.choice(candidates)


def record_done(task: dict, turn_id: str, summary: str) -> None:
    """记录一次任务执行结果（append-only）。"""
    p = task_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "title": task["title"],
        "turn_id": turn_id,
        "summary": summary[:500],
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def iter_tasks(stop_check) -> Iterator[dict]:
    """无限迭代任务。stop_check() 返回 True 时退出。"""
    rng = random.Random()
    rng.seed()  # 每次启动随机性不同
    while not stop_check():
        yield next_task(rng)
