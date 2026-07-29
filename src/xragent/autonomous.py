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


# 任务模板：每个都强制 write_file 改 src/，不接受的"只读"task
TASK_TEMPLATES = [
    {
        "title": "改一处 src 性能可读性",
        "prompt": (
            "读 src/xragent/ 下任一模块，必须用 write_file 改至少 3 行（不能只读）。\n"
            "目标：性能 / 可读性 / 边界条件 / 抽公共函数 / 简化 if-else。\n"
            "改完跑 scripts/test；如失败 git checkout -- <file> 回滚再换下一个。\n"
            "commit message 里写清楚：改了什么、为什么、改了几行。"
        ),
    },
    {
        "title": "改一处工具实现",
        "prompt": (
            "读 src/xragent/tools/ 下某个工具（fs_tools/exec_tools/git_tools/memory_tools/diary_tools/evolve_tools）。\n"
            "必须用 write_file 改：加新参数 / 改错误处理 / 加 timeout / 抽公共 helper / 加 type hint。\n"
            "改完跑 scripts/test；新增测试加到 tests/test_*.py 覆盖改动。\n"
            "commit message 写：why + diff stat。"
        ),
    },
    {
        "title": "改 schema 或加 API",
        "prompt": (
            "读 src/xragent/memory/manager.py 或 src/xragent/snapshot/side_git.py，\n"
            "必须 write_file 改：加 SQLite 索引 / 加新方法 / 改 dataclass 字段 / 改返回类型。\n"
            "改完跑 PYTHONPATH=src python3.11 -m pytest tests/test_memory.py tests/test_sidegit.py -v。\n"
            "schema 改动要写 migration 注释（5.0 → 5.1: 加 source_turn_idx）。"
        ),
    },
    {
        "title": "重构抽公共函数",
        "prompt": (
            "找 src/xragent/ 下两个 .py 文件里重复出现的 5+ 行代码（try/except、JSON 解析、\n"
            "git 命令、format timestamp 之类），抽到 src/xragent/util/ 或合适位置。\n"
            "必须 write_file 改两个原文件 + 1 个新 util 文件。\n"
            "改完跑 scripts/test 确认 0 regression。"
        ),
    },
    {
        "title": "加 type hint 与 docstring",
        "prompt": (
            "读 src/xragent/ 下 1-2 个 .py，找函数没 type hint 或 docstring 缺失的，\n"
            "必须 write_file 加上 type hint（PEP 604: int | None）+ Google-style docstring。\n"
            "改完跑 scripts/test。commit message 写：typing: <files> 共加 N 个 hint。"
        ),
    },
    {
        "title": "加新功能小而具体",
        "prompt": (
            "挑一个没做但应该做的小功能，写到 src/xragent/。\n"
            "候选：\n"
            "  - memory 工具：按 ts 范围 recall / top-N 频繁 fact\n"
            "  - snapshot：清理 30 天前的 snapshot tag\n"
            "  - blacklist：支持更复杂的 binary 黑名单 pattern（regex）\n"
            "  - diary：自动按周归档 diary/*.md\n"
            "必须 write_file + 加 1 个测试。改完跑 scripts/test。"
        ),
    },
    {
        "title": "写 ADR 设计决策",
        "prompt": (
            "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。\n"
            "必须 write_file 改 docs/architecture-v0.md 或加 docs/adr/0001-*.md（设计决策记录）。\n"
            "改完 commit。"
        ),
    },
    {
        "title": "金蝉脱壳演练仅当有 src 改动时",
        "prompt": (
            "检查 git diff origin/main..HEAD：\n"
            "  - 如果含 src/ 改动 → commit → push → py_compile → 写 evolve/generations.jsonl 一行 → 推 push\n"
            "  - 如果无 src 改动 → 直接 git revert HEAD --no-edit 把上一条 autonomous commit 撤回（避免空转）"
        ),
    },
]


def task_queue_path() -> Path:
    """Agent 自己的任务队列（不入 git）。"""
    s = get_settings()
    return s.repo_root / "memory" / "queue.jsonl"


def task_cooldown_key(task: dict) -> str:
    return task["title"]


DEFAULT_COOLDOWN_S = 7200.0


def _recent_titles(window_s: float = DEFAULT_COOLDOWN_S) -> set[str]:
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




# === autonomous turn-11 patch ===
# 把任务模板按"风险/收益"排序(优先小改动);冷却从 1h 改 2h。
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
    rng.seed()
    while not stop_check():
        yield next_task(rng)
