"""memory 工具层 ``_clip_limit`` 兜底行为测试。

聚焦: LLM 传"恶意/失控"参数 (0 / 负数 / 字符串 / 巨大数 / None / bool)
时, memory_recall / memory_recall_range / memory_top_frequent 三个工具
是否走 :func:`xragent.tools.memory_tools._clip_limit` 统一兜底, 而不是
把异常值原样转给底层 SQLite LIMIT / GROUP BY。

不重复 test_memory_tools.py / test_memory_tools_wrappers.py 覆盖的
"主路径" 和 "wrapper 形状" 测试, 本文件专门锁数字参数边界。
"""
from __future__ import annotations

import pytest

from xragent.memory.manager import MemoryManager
from xragent.tools.memory_tools import (
    _K_LIMIT_MAX,
    _K_LIMIT_MIN,
    _MIN_COUNT_LIMIT_MAX,
    _MIN_COUNT_LIMIT_MIN,
    _clip_limit,
    memory_recall,
    memory_recall_range,
    memory_top_frequent,
)


# === _clip_limit helper 单元测试 (不依赖 DB) ==============================

class TestClipLimitHelper:
    """``_clip_limit`` 本身的纯函数行为。"""

    def test_normal_int_in_range_unchanged(self) -> None:
        assert _clip_limit(5, default=5, lo=1, hi=1000) == 5

    def test_boundary_lo(self) -> None:
        assert _clip_limit(1, default=5, lo=1, hi=1000) == 1

    def test_boundary_hi(self) -> None:
        assert _clip_limit(1000, default=5, lo=1, hi=1000) == 1000

    def test_zero_clipped_to_lo(self) -> None:
        assert _clip_limit(0, default=5, lo=1, hi=1000) == 1

    def test_negative_clipped_to_lo(self) -> None:
        assert _clip_limit(-100, default=5, lo=1, hi=1000) == 1

    def test_above_hi_clipped_to_hi(self) -> None:
        assert _clip_limit(999_999, default=5, lo=1, hi=1000) == 1000

    def test_none_uses_default(self) -> None:
        assert _clip_limit(None, default=5, lo=1, hi=1000) == 5

    def test_str_numeric_coerced(self) -> None:
        assert _clip_limit("7", default=5, lo=1, hi=1000) == 7

    def test_float_coerced_via_int_truncation(self) -> None:
        # int(7.9) == 7, 与"字符串/浮点也走 int 强转"一致
        assert _clip_limit(7.9, default=5, lo=1, hi=1000) == 7

    def test_garbage_str_uses_default(self) -> None:
        assert _clip_limit("not-a-number", default=5, lo=1, hi=1000) == 5

    def test_list_uses_default(self) -> None:
        # LLM 偶尔把 list 当 number, 应该被识别为非法
        assert _clip_limit([5], default=5, lo=1, hi=1000) == 5

    def test_bool_true_treated_as_invalid(self) -> None:
        # bool 是 int 的子类, 但 LLM 传 True 当数字是 bug, 走 default
        assert _clip_limit(True, default=5, lo=1, hi=1000) == 5

    def test_bool_false_treated_as_invalid(self) -> None:
        # 否则 False → 0 → clip 到 lo=1, 看似 OK 但语义是"未指定"
        assert _clip_limit(False, default=5, lo=1, hi=1000) == 5

    def test_default_value_always_in_range(self) -> None:
        # 防御: 调用方传一个超出区间的 default 也应该被夹回去
        assert _clip_limit("junk", default=9999, lo=1, hi=10) == 10
        assert _clip_limit("junk", default=-5, lo=1, hi=10) == 1

    def test_module_constants_consistent(self) -> None:
        """模块级常量值是 LLM-facing 契约的一部分 (被 README/外部文档引用),
        改值要慎重。本测试防止有人手抖把上下界改反。"""
        assert _K_LIMIT_MIN == 1
        assert _K_LIMIT_MAX == 1000
        assert _MIN_COUNT_LIMIT_MIN == 1
        assert _MIN_COUNT_LIMIT_MAX == 10_000


# === memory_recall (关键词 LIKE 路径) 边界测试 ============================

class TestMemoryRecallClip:
    """memory_recall 的 k 参数走 _clip_limit 兜底。"""

    def test_k_zero_clipped_to_one(self, repo_root) -> None:
        # k=0 经 _clip_limit 后变 1, 不应返回空
        m = MemoryManager()
        m.save_fact("note", "hello")
        out = memory_recall(query="hello", k=0)
        assert out["count"] == 1
        assert out["facts"][0]["content"] == "hello"

    def test_k_negative_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "world")
        out = memory_recall(query="world", k=-5)
        assert out["count"] == 1

    def test_k_above_limit_clipped(self, repo_root) -> None:
        m = MemoryManager()
        for i in range(3):
            m.save_fact("note", f"item {i}")
        # k=10_000 应被夹到 1000, 但库内只有 3 条, 仍能正常返回 3
        out = memory_recall(query="item", k=10_000)
        assert out["count"] == 3

    def test_k_string_coerced(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "coerce-me")
        out = memory_recall(query="coerce-me", k="2")
        # 字符串 "2" 强转成 2, 不抛 TypeError
        assert out["count"] == 1
        assert out["ok"] is True

    def test_k_garbage_string_falls_back_to_default(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "fallback")
        out = memory_recall(query="fallback", k="definitely-not-a-number")
        # 非法值走 default=5, 不抛 TypeError
        assert out["ok"] is True
        assert out["count"] == 1


# === memory_recall_range (时间窗口路径) 边界测试 =========================

class TestMemoryRecallRangeClip:
    """memory_recall_range 之前没 k 兜底, 是这次 refactor 的重点修复点。"""

    def test_k_zero_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "range-1")
        # 之前 k=0 会让 LIMIT 0 直接返回空; 现在应被夹到 1
        out = memory_recall_range(k=0)
        assert out["ok"] is True
        assert out["count"] >= 1

    def test_k_negative_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "range-2")
        out = memory_recall_range(k=-1)
        assert out["ok"] is True
        assert out["count"] >= 1

    def test_k_huge_clipped_to_1000(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "range-3")
        out = memory_recall_range(k=10**9)
        # 库内只有 1 条, 但函数应能正常返回 (不抛 MemoryError / 不超时)
        assert out["ok"] is True
        assert out["count"] == 1

    def test_k_string_coerced(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "range-4")
        out = memory_recall_range(k="3")
        assert out["ok"] is True
        assert out["count"] == 1


# === memory_top_frequent (频次聚合路径) 边界测试 =========================

class TestMemoryTopFrequentClip:
    """memory_top_frequent 的 n / min_count 都应走 _clip_limit。"""

    def test_n_zero_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-1")
        # n=0 → LIMIT 0 → 空结果; 夹到 1 后应能拿到 1 条
        out = memory_top_frequent(n=0, min_count=1)
        assert out["ok"] is True
        assert out["count"] == 1

    def test_n_negative_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-2")
        out = memory_top_frequent(n=-10, min_count=1)
        assert out["ok"] is True
        assert out["count"] == 1

    def test_n_huge_clipped(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-3")
        out = memory_top_frequent(n=10**9, min_count=1)
        assert out["ok"] is True

    def test_min_count_zero_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-4")
        # min_count=0 → HAVING c >= 0 (恒真) → 正常; 夹到 1 仍正常
        out = memory_top_frequent(n=5, min_count=0)
        assert out["ok"] is True
        assert out["count"] == 1

    def test_min_count_negative_clipped_to_one(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-5")
        out = memory_top_frequent(n=5, min_count=-99)
        assert out["ok"] is True
        assert out["count"] == 1

    def test_min_count_huge_clipped(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-6")
        out = memory_top_frequent(n=5, min_count=10**9)
        # min_count 远大于 1 (库内只 1 条) → 0 命中; ok=True, count=0
        assert out["ok"] is True
        assert out["count"] == 0
        assert out["top"] == []

    def test_n_string_coerced(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-7")
        out = memory_top_frequent(n="2", min_count="1")
        assert out["ok"] is True
        assert out["count"] == 1

    def test_garbage_min_count_falls_back_to_default(self, repo_root) -> None:
        m = MemoryManager()
        m.save_fact("note", "freq-8")
        m.save_fact("note", "freq-8")  # 同 content 出现 2 次
        out = memory_top_frequent(n=5, min_count="not-a-number")
        # 非法值走 default=2, "freq-8" 出现 2 次应入选
        assert out["ok"] is True
        assert out["count"] == 1
        assert out["top"][0]["content"] == "freq-8"


# === 三个工具之间的行为对齐 (cross-tool contract) ========================

class TestThreeToolsBehaviorAligned:
    """_clip_limit 抽离的目标: 三个工具面对同样"垃圾输入"应表现一致。"""

    @pytest.mark.parametrize("garbage", [0, -1, -999, None, "abc", True, False, [9]])
    def test_memory_recall_never_raises_on_garbage_k(self, repo_root, garbage: object) -> None:
        m = MemoryManager()
        m.save_fact("note", "x")
        out = memory_recall(query="x", k=garbage)  # type: ignore[arg-type]
        assert out["ok"] is True
        assert out["count"] == 1

    @pytest.mark.parametrize("garbage", [0, -1, -999, None, "abc", True, False])
    def test_memory_recall_range_never_raises_on_garbage_k(
        self, repo_root, garbage: object
    ) -> None:
        m = MemoryManager()
        m.save_fact("note", "x")
        out = memory_recall_range(k=garbage)  # type: ignore[arg-type]
        assert out["ok"] is True

    @pytest.mark.parametrize("garbage_n", [0, -1, None, "abc", True, False])
    @pytest.mark.parametrize("garbage_mc", [0, -1, None, "abc"])
    def test_memory_top_frequent_never_raises_on_garbage_params(
        self, repo_root, garbage_n: object, garbage_mc: object
    ) -> None:
        m = MemoryManager()
        m.save_fact("note", "x")
        out = memory_top_frequent(  # type: ignore[arg-type]
            n=garbage_n, min_count=garbage_mc
        )
        assert out["ok"] is True
