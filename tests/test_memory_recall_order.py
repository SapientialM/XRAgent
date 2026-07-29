"""memory_recall_range 输出按 ts DESC 排序（newest first）。

为什么这个 case 单独立:
    tests/test_memory_tools.py 已经用 time.sleep(0.05) 创造间隔间接验证了
    顺序, 但**没有**任何一个 case 直接断言 "ts_list 是降序的"。
    对 LLM agent 来说这是契约: 拿到的第一个 fact 就应该是最新的, 不能让
    并列 ts 被乱序。本文件锁定这条, 防止以后有人为了"性能优化"把 ORDER BY
    去掉或改成 ASC。

锁定契约:
    - 不传 start_ts/end_ts = 开放区间
    - ts 严格降序
    - count == len(facts) (与 test_memory_tools_wrappers.test_recall_range_respects_k_param 一致)
    - facts 元素至少含 id / ts / category / content 字段 (LLM 调用路径的最小集)
"""
from __future__ import annotations

import time

from xragent.memory.manager import MemoryManager
from xragent.tools.memory_tools import memory_recall_range


def test_recall_range_returns_ts_desc(repo_root):
    """三条 fact 顺序写入, 召回必须 newest-first。"""
    m = MemoryManager()
    m.save_fact("note", "first")
    time.sleep(0.02)
    m.save_fact("note", "second")
    time.sleep(0.02)
    m.save_fact("note", "third")

    out = memory_recall_range()

    assert out["ok"] is True
    assert out["count"] == 3
    assert len(out["facts"]) == 3

    # 内容顺序: third → second → first (newest first)
    contents = [f["content"] for f in out["facts"]]
    assert contents == ["third", "second", "first"], (
        f"期望 ts DESC, 实际顺序 {contents}"
    )

    # ts 严格降序 (并列时也要稳定, 不允许被乱序)
    ts_list = [f["ts"] for f in out["facts"]]
    assert ts_list == sorted(ts_list, reverse=True), (
        f"ts 不是降序: {ts_list}"
    )


def test_recall_range_fact_dict_shape(repo_root):
    """fact 元素必须含 LLM 需要的最小字段集。

    防有人为了"瘦身"去掉 ts 或 category, 让 LLM 拿到的 fact 缺上下文。
    """
    m = MemoryManager()
    m.save_fact("preference", "user 喜欢简洁")

    out = memory_recall_range()
    assert out["count"] == 1
    fact = out["facts"][0]
    assert set(fact.keys()) >= {"id", "ts", "category", "content"}
    assert fact["category"] == "preference"
    assert fact["content"] == "user 喜欢简洁"
    assert isinstance(fact["id"], int)
    assert isinstance(fact["ts"], float)


def test_recall_range_start_ts_only_excludes_past(repo_root):
    """只传 start_ts, 之前的 fact 必须被排除 (manager 端 < 已经验证, 这里再锁 wrapper 透传)。"""
    m = MemoryManager()
    m.save_fact("note", "before")
    time.sleep(0.05)
    t_cut = time.time()
    time.sleep(0.05)
    m.save_fact("note", "after")

    out = memory_recall_range(start_ts=t_cut)

    assert out["ok"] is True
    contents = [f["content"] for f in out["facts"]]
    assert "after" in contents
    assert "before" not in contents
    assert out["count"] == 1