"""自驱动循环：无人值守时按 task templates 循环推进。

不是 AGI，是「按一份多元化任务清单 + ReAct 循环 + commit」，
让它在没人在的时候也能稳定推进：加测试 / 改文档 / 重构 / 优化 prompt。
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from .config.settings import get_settings
from .util.jsonl_utils import append_jsonl, iter_jsonl


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
            "  - 如果无 src/ 改动 → 直接 git revert HEAD --no-edit 把上一条 autonomous commit 撤回（避免空转）"
        ),
    },
]


def task_queue_path() -> Path:
    """返回 Agent 任务队列文件路径（``memory/queue.jsonl``，不入 git）。

    Returns:
        queue.jsonl 的绝对路径（``Settings.repo_root / memory/queue.jsonl``）。
    """
    s = get_settings()
    return s.repo_root / "memory" / "queue.jsonl"


def task_cooldown_key(task: dict[str, Any]) -> str:
    """取任务唯一 key（用 ``title`` 字段）用于 cooldown 去重。

    Args:
        task: 任务模板 dict（来自 :data:`TASK_TEMPLATES`）；必须有 ``title`` 键。

    Returns:
        ``task["title"]``；缺失时返回空字符串（保持类型稳定）。
    """
    return task["title"]


DEFAULT_COOLDOWN_S: float = 7200.0

# summary 截断上限（保护 queue.jsonl 不被超长字段撑爆；提到模块常量便于测试 import 锁契约）
_MAX_SUMMARY_CHARS: int = 500


def _recent_titles(window_s: float = DEFAULT_COOLDOWN_S) -> set[str]:
    """返回最近 window_s 秒内做过的任务 title 集合（用于 cooldown）。

    之前这里手写 5+ 行 read_text → splitlines → strip → safe_json_loads → 过滤 None
    块（与 ``evolve/generations.py::list_generations`` 完全同构），现抽到
    ``util.jsonl_utils.iter_jsonl``，调用方只剩一行 for 循环。

    Args:
        window_s: 时间窗口（秒）；默认 ``DEFAULT_COOLDOWN_S``（2h）。

    Returns:
        窗口内出现过的 task title 集合；queue 文件不存在时返回空 set。
    """
    p = task_queue_path()
    if not p.exists():
        return set()
    cutoff = time.time() - window_s
    seen: set[str] = set()
    for rec in iter_jsonl(p):
        # rec 必须是 dict；非 dict（list/str/标量）跳过
        if not isinstance(rec, dict):
            continue
        # ts 必须是数字（且不是 bool，bool 是 int 子类会被静默吞）
        ts = rec.get("ts")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        if ts >= cutoff:
            seen.add(rec.get("title", ""))
    return seen


def next_task(
    rng: random.Random | None = None,
    window_s: float = DEFAULT_COOLDOWN_S,
) -> dict[str, Any]:
    """从 templates 选一个不在 cooldown 里的任务。

    cooldown：同 title ``window_s`` 秒内不重复；``window_s`` 可调，便于
    测试时短时间绕过冷却。全冷却时返回 ``TASK_TEMPLATES[0]``，让
    Agent 自己想办法或蜕皮。

    Args:
        rng: 可选随机源；``None`` 时用模块级 :mod:`random`。传入 ``Random``
            实例便于测试时固定种子。
        window_s: cooldown 时间窗口（秒）；默认 ``DEFAULT_COOLDOWN_S``（2h）。

    Returns:
        选中的任务 dict（来自 :data:`TASK_TEMPLATES`）。
    """
    rng = rng or random
    candidates = [
        t for t in TASK_TEMPLATES
        if task_cooldown_key(t) not in _recent_titles(window_s)
    ]
    if not candidates:
        # 硬退化：所有模板都还在 cooldown，返回 [0] 让 Agent 自己想办法。
        # 用索引而非 title 字面量，避免模板表顺序漂移时悄悄换 fallback。
        return TASK_TEMPLATES[0]
    return rng.choice(candidates)


def record_done(task: dict[str, Any], turn_id: str, summary: str) -> None:
    """记录一次任务执行结果（append-only）。

    Args:
        task: 已完成的任务 dict（来自 TASK_TEMPLATES）。
        turn_id: 当前 turn 标识（用于 diary 回溯）。
        summary: 完成情况描述，会被截断到 500 字符。

    Note:
        历史 here 手写 ``p.parent.mkdir + open(a) + json.dumps + write`` 共 5 行，
        与 ``util.jsonl_utils.append_jsonl``（同模式）重复。改成调用 helper 后
        行为不变（同样 ensure_ascii=False + 末尾 \\n + mkdir parent），但去掉了
        一处可能漂移的复制粘贴。
    """
    rec = {
        "ts": time.time(),
        "title": task["title"],
        "turn_id": turn_id,
        "summary": summary[:_MAX_SUMMARY_CHARS],
    }
    append_jsonl(task_queue_path(), rec)


def iter_tasks(stop_check: Callable[[], bool]) -> Iterator[dict[str, Any]]:
    """无限迭代任务。stop_check() 返回 True 时退出。

    Args:
        stop_check: 无参 callable，返回 True 时让生成器停。

    Yields:
        dict: 选中的任务模板。
    """
    # random.Random() 构造器已经默认用 os.urandom seed；再调一次 rng.seed()
    # 只会再触发一次 entropy pull，纯冗余（同时让测试看不出"是不是真 seed 过"）。
    rng = random.Random()
    while not stop_check():
        yield next_task(rng)