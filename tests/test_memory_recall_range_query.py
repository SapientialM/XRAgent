"""``memory_recall_range`` 的 ``query`` (LIKE 关键词) 参数测试。5.9 新增。

聚焦三件事:
1. ``query`` 非空 → 叠加 ``content LIKE %q%`` 过滤 (manager + tool 两层)
2. ``query`` 空 / 纯空白 → 不过滤, 与既有 ``category`` 一致 (向后兼容)
3. ``query`` 与 ``start_ts`` / ``end_ts`` / ``category`` 可任意组合,
   单调用完成"时间段 + 关键词 + 分类" 三维过滤。

不在本文件覆盖: ``query`` 本身的 LIKE 通配符语义 (与 ``memory_recall``
行为一致, 不重复锁) ; ``k`` 兜底 (走 ``test_memory_tools_clip``)。
"""
from __future__ import annotations

import pytest

from xragent.memory.manager import MemoryManager
from xragent.tools.memory_tools import memory_recall_range


@pytest.fixture
def seeded_manager(repo_root) -> MemoryManager:
    """准备 3 条 fact (不同 ts + category + content), 验证 LIKE 过滤行为。"""
    m = MemoryManager()
    # ts 升序, 后续断言按 ts DESC 校验顺序。
    m.save_fact(category="note", content="父母提到过 git rebase")  # ts=oldest
    m.save_fact(category="note", content="今天 commit 了半天")
    m.save_fact(category="task", content="git push 之前要先 archive 周报")  # ts=newest
    return m


# === manager 层 ===========================================================


class TestRecallRangeQueryManager:
    """MemoryManager.recall_range(query=...) 直接调用。"""

    def test_query_hits_subset(self, seeded_manager: MemoryManager) -> None:
        out = seeded_manager.recall_range(query="git")
        contents = [f.content for f in out]
        # 只剩 "git rebase" + "git push" 两条; "commit" 不在 LIKE 命中里。
        assert contents == [
            "git push 之前要先 archive 周报",
            "父母提到过 git rebase",
        ]

    def test_query_empty_string_is_no_filter(self, seeded_manager: MemoryManager) -> None:
        out_empty = seeded_manager.recall_range(query="")
        out_unset = seeded_manager.recall_range()
        # query="" 不应改变结果集; 与不传参数完全一致。
        c_empty = [f.content for f in out_empty]
        c_unset = [f.content for f in out_unset]
        assert c_empty == c_unset
        assert len(c_empty) == 3

    def test_query_whitespace_only_is_no_filter(
        self, seeded_manager: MemoryManager
    ) -> None:
        out_ws = seeded_manager.recall_range(query="   \t  ")
        out_default = seeded_manager.recall_range()
        assert [f.content for f in out_ws] == [f.content for f in out_default]

    def test_query_no_match_returns_empty(self, seeded_manager: MemoryManager) -> None:
        assert seeded_manager.recall_range(query="zzz不可能命中zzz") == []

    def test_query_combined_with_category(self, seeded_manager: MemoryManager) -> None:
        out = seeded_manager.recall_range(query="git", category="task")
        contents = [f.content for f in out]
        # category=task 下只剩 "git push ..." 一条
        assert contents == ["git push 之前要先 archive 周报"]

    def test_query_combined_with_time_window(self, seeded_manager: MemoryManager) -> None:
        m = seeded_manager
        all_ts = [f.ts for f in m.recall_range()]
        t_min, t_max = min(all_ts), max(all_ts)
        # start_ts > max(ts) → 时间窗口内什么都没有, query 命中也救不回来
        out_future = m.recall_range(query="git", start_ts=t_max + 1.0)
        assert out_future == []
        # end_ts < min(ts) → 同理
        out_past = m.recall_range(query="git", end_ts=t_min - 1.0)
        assert out_past == []
        # 放宽窗口 [t_min-1, t_max+1] → query "git" 命中 2 条
        out_all = m.recall_range(
            query="git", start_ts=t_min - 1.0, end_ts=t_max + 1.0
        )
        assert len(out_all) == 2
        assert all("git" in f.content for f in out_all)


# === tool wrapper 层 ======================================================


class TestMemoryRecallRangeQueryTool:
    """``memory_recall_range`` 工具层的 contract 锁定 (LLM-facing)。"""

    def test_query_default_is_empty_string(self, seeded_manager: MemoryManager) -> None:
        """默认参数 ``query=""`` → 与不传 ``query`` 完全等价, 不破坏旧调用。"""
        out_default = memory_recall_range()
        out_explicit_empty = memory_recall_range(query="")
        assert out_default["ok"] is True
        assert out_explicit_empty["ok"] is True
        assert out_default["count"] == out_explicit_empty["count"] == 3

    def test_query_filters_in_tool(self, seeded_manager: MemoryManager) -> None:
        out = memory_recall_range(query="commit")
        assert out["ok"] is True
        assert out["count"] == 1
        # 字段集是 LLM 契约, 锁 4 字段
        fact = out["facts"][0]
        assert set(fact.keys()) == {"id", "ts", "category", "content"}
        assert "commit" in fact["content"]

    def test_query_combined_with_category_in_tool(
        self, seeded_manager: MemoryManager
    ) -> None:
        out = memory_recall_range(query="git", category="task", k=10)
        assert out["ok"] is True
        assert out["count"] == 1
        assert out["facts"][0]["category"] == "task"
        assert "git" in out["facts"][0]["content"]

    def test_query_with_zero_k_still_clipped(self, seeded_manager: MemoryManager) -> None:
        """``query`` 与 ``k`` 兜底正交: k=0 走 clip, query 仍生效。"""
        out = memory_recall_range(query="git", k=0)
        # k=0 → clip 到 1, 不应返回 0 条 (否则违反 _clip_limit 契约)
        assert out["ok"] is True
        assert out["count"] >= 1
        assert all("git" in f["content"] for f in out["facts"])