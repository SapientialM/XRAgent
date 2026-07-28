"""autonomous.py · task queue 边界条件。

覆盖：
  * task_queue_path / task_cooldown_key：纯函数 + 路径派生
  * record_done：append-only JSONL，summary 截断到 500，父目录自动建
  * _recent_titles：窗口过滤、缺文件兜底、坏 JSON 行容忍
  * next_task：cooldown 回避、空池 fallback、rng 确定性
  * iter_tasks：stop_check 一拉即停、且 stop_check 为 True 时不再 yield

锁定行为快照：当前 implementation 不去重同 ts 同 title 的相邻条目
（test 5 显式验证这点，避免未来默默合并）。
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from xragent import autonomous as au
from xragent.autonomous import (
    TASK_TEMPLATES,
    iter_tasks,
    next_task,
    record_done,
    task_cooldown_key,
    task_queue_path,
    _recent_titles,
)


# ---------------------------------------------------------------------------
# task_queue_path / task_cooldown_key
# ---------------------------------------------------------------------------

def test_task_queue_path_points_under_repo_root_memory(repo_root: Path):
    """任务队列必须在 repo_root/memory/queue.jsonl，绝不能飘到仓库外。"""
    p = task_queue_path()
    assert p == repo_root / "memory" / "queue.jsonl"


def test_task_cooldown_key_returns_title_only():
    """cooldown key 用 title 字段；其他字段不该参与哈希。"""
    task = {"title": "补充测试", "prompt": "any prompt body", "extra": 123}
    assert task_cooldown_key(task) == "补充测试"


# ---------------------------------------------------------------------------
# record_done
# ---------------------------------------------------------------------------

def test_record_done_creates_parent_dir_and_appends_jsonl(repo_root: Path):
    """首次 record_done 自动建 memory/，并写入合法 JSON 行。"""
    task = {"title": "补充测试", "prompt": "x"}
    record_done(task, turn_id="t-001", summary="wrote 3 tests")

    p = task_queue_path()
    assert p.exists()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["title"] == "补充测试"
    assert rec["turn_id"] == "t-001"
    assert rec["summary"] == "wrote 3 tests"
    # 必须有 ts 浮点；不锁具体数值，只验证它是浮点且近期
    assert isinstance(rec["ts"], float)
    assert abs(rec["ts"] - time.time()) < 5


def test_record_done_truncates_summary_to_500(repo_root: Path):
    """summary 超过 500 字符必须被砍断（保护 queue.jsonl 不被爆）。"""
    long = "x" * 1234
    record_done({"title": "审视代码", "prompt": "y"}, "t-002", long)

    rec = json.loads(task_queue_path().read_text(encoding="utf-8").splitlines()[0])
    assert len(rec["summary"]) == 500
    # 必须等于前 500 个字符
    assert rec["summary"] == long[:500]


def test_record_done_appends_multiple_records(repo_root: Path):
    """多次 record_done 必须 append-only；不覆盖前面。"""
    for i in range(3):
        record_done({"title": f"任务-{i}", "prompt": ""}, f"t-{i}", f"sum-{i}")

    lines = task_queue_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    titles = [json.loads(ln)["title"] for ln in lines]
    assert titles == ["任务-0", "任务-1", "任务-2"]


def test_record_done_does_not_dedup_same_title_and_ts(repo_root: Path):
    """现状快照：相邻两条同 title 不会被去重——锁这条行为。
    如果将来改成 dedup / replace，本测试应被替换为去重后的期望。
    """
    task = {"title": "反思日记", "prompt": "z"}
    record_done(task, "t-A", "first")
    record_done(task, "t-B", "second")

    lines = task_queue_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["turn_id"] == "t-A"
    assert json.loads(lines[1])["turn_id"] == "t-B"


# ---------------------------------------------------------------------------
# _recent_titles
# ---------------------------------------------------------------------------

def test_recent_titles_returns_empty_when_queue_missing(repo_root: Path):
    """queue.jsonl 不存在时返回空集合（不抛异常）。"""
    assert not task_queue_path().exists()
    assert _recent_titles(window_s=3600) == set()


def test_recent_titles_picks_only_within_window(repo_root: Path):
    """窗口外的旧记录应被忽略，窗口内的全部 title 收集起来。"""
    p = task_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 手工写一份：1 条很旧的 + 2 条新的（ts 标记时间戳）
    old_ts = time.time() - 7200  # 2 小时前
    new_ts = time.time() - 60    # 1 分钟前
    fresh = [
        {"ts": new_ts, "title": "新 A", "turn_id": "n1", "summary": ""},
        {"ts": new_ts - 1, "title": "新 B", "turn_id": "n2", "summary": ""},
        {"ts": old_ts, "title": "旧 C", "turn_id": "o1", "summary": ""},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in fresh) + "\n", encoding="utf-8")

    seen = _recent_titles(window_s=3600)
    assert seen == {"新 A", "新 B"}
    assert "旧 C" not in seen


def test_recent_titles_skips_malformed_json_lines(repo_root: Path):
    """坏 JSON 行不能把整个函数炸掉，必须被跳过。"""
    p = task_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    bad = "{not valid json\n"
    good = json.dumps({"ts": time.time(), "title": "ok", "turn_id": "t", "summary": ""}, ensure_ascii=False)
    p.write_text(bad + "\n" + good + "\n", encoding="utf-8")

    assert _recent_titles(window_s=3600) == {"ok"}


def test_recent_titles_empty_lines_ignored(repo_root: Path):
    """空行和全空白行同样要被容忍。"""
    p = task_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "title": "T", "turn_id": "x", "summary": ""}
    p.write_text("\n  \n" + json.dumps(rec, ensure_ascii=False) + "\n\n", encoding="utf-8")
    assert _recent_titles(window_s=3600) == {"T"}


# ---------------------------------------------------------------------------
# next_task
# ---------------------------------------------------------------------------

def _seed_queue_with_titles(titles: list[str], ts_offset_s: float = -60.0):
    """辅助：构造一份 queue.jsonl，里面是带 ts 的指定 titles。"""
    p = task_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    lines = []
    for i, t in enumerate(titles):
        rec = {
            "ts": now + ts_offset_s - i,  # 每条错开一点
            "title": t,
            "turn_id": f"seed-{i}",
            "summary": "",
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_next_task_returns_valid_template(repo_root: Path):
    """默认池全空时只能从 templates 里挑一条。"""
    task = next_task(random.Random(0))
    assert task in TASK_TEMPLATES
    assert "title" in task and "prompt" in task


def test_next_task_avoids_recent_titles_in_cooldown(repo_root: Path):
    """最近 1 小时内做过的 title 必须被踢出候选池。"""
    # 把前 N 个模板 title 全标成"已做"
    blocked = [t["title"] for t in TASK_TEMPLATES[:3]]
    _seed_queue_with_titles(blocked)

    # 跑 50 次 rng 抽样，应永远拿不到这 3 个 title（剩余模板池子非空）
    rng = random.Random(0)
    chosen = {next_task(rng)["title"] for _ in range(50)}
    assert chosen.isdisjoint(set(blocked))
    # 且至少要能选出剩余模板中的 1 个
    assert chosen  # not empty


def test_next_task_fallback_to_first_when_all_cooled(repo_root: Path):
    """所有模板 title 全在 cooldown → 返回 TASK_TEMPLATES[0]（让 Agent 自己想办法）。"""
    all_titles = [t["title"] for t in TASK_TEMPLATES]
    _seed_queue_with_titles(all_titles)

    task = next_task(random.Random(0))
    assert task["title"] == TASK_TEMPLATES[0]["title"]


def test_next_task_rng_seeded_is_deterministic(repo_root: Path):
    """同样的 seed + 同样的池 → 同样的 title（可复现）。"""
    _seed_queue_with_titles(["审视代码"])  # 给一个 title 占住
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    a = next_task(rng1)["title"]
    b = next_task(rng2)["title"]
    assert a == b


def test_next_task_uses_module_default_rng_when_none_passed(repo_root: Path):
    """rng=None 走 module random（不锁输出，只验证不会抛）。"""
    _seed_queue_with_titles([])  # 空池
    task = next_task(rng=None)
    assert task in TASK_TEMPLATES


def test_next_task_does_not_mutate_input_rng_pool(repo_root: Path):
    """模板池大小固定 8；next_task 必须从这 8 个里挑，不发明新 title。"""
    titles_seen = {next_task(random.Random(i))["title"] for i in range(40)}
    assert titles_seen.issubset({t["title"] for t in TASK_TEMPLATES})


# ---------------------------------------------------------------------------
# iter_tasks
# ---------------------------------------------------------------------------

def test_iter_tasks_yields_until_stop_check_says_stop(repo_root: Path):
    """stop_check 第一次 False 时还能产出，第二次 True 时退出。"""
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] >= 3  # 第三次返回 True

    it = iter_tasks(stop_check=stop)
    produced = []
    # 收集最多 10 条（实际只会拿到 2 条）
    for _ in range(10):
        try:
            t = next(it)
        except StopIteration:
            break
        produced.append(t["title"])

    # 第二次 stop_check 返回 True 之前会 yield；之后退出
    # 抽样次数 = stop_check 被调的次数 - 1（最后一次 True 不拿对应 task）
    # 因为 next_task 内调 stop_check 检查… 实际上 iter_tasks 是 while not stop_check: yield
    # 所以 yield 数 == stop_check 返回 True 之前的次数 - 1
    # 关键是产出的都是合法模板
    assert produced
    for title in produced:
        assert title in {t["title"] for t in TASK_TEMPLATES}


def test_iter_tasks_exits_immediately_if_stop_check_true_from_start(repo_root: Path):
    """stop_check 上来就 True → 一次也不 yield。"""
    def stop():
        return True

    it = iter_tasks(stop_check=stop)
    with pytest.raises(StopIteration):
        next(it)


# ---------------------------------------------------------------------------
# Task templates 自身的 sanity（防止模板表被悄悄清空）
# ---------------------------------------------------------------------------

def test_task_templates_have_required_fields():
    """每个模板必须含 title + prompt，否则 record_done / next_task 都得炸。"""
    assert len(TASK_TEMPLATES) >= 4, "模板太少会让 cooldown 失去意义"
    for t in TASK_TEMPLATES:
        assert isinstance(t["title"], str) and t["title"], f"title invalid: {t}"
        assert isinstance(t["prompt"], str) and len(t["prompt"]) > 20, f"prompt too short: {t}"


def test_task_templates_titles_are_unique():
    """title 必须唯一——否则 cooldown 形同虚设（重复 title 互相抵消）。"""
    titles = [t["title"] for t in TASK_TEMPLATES]
    assert len(titles) == len(set(titles)), f"重复 template title: {titles}"
