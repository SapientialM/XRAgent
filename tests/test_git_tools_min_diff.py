"""git_tools: _normalize_min_diff_bytes / _commit_result / min_diff_bytes 参数契约.

git_tools.git_commit 原先 hardcode ``min_diff_bytes=0`` (有意设计:
Agent 显式 commit 应该尽量提交)。本次重构把它暴露为关键字参数 + 加两个
helper 把所有边界统一管理。tests/test_git_tools.py 已锁住 3 键 LLM 契约,
本文件只测新增的纯函数 + git_commit 的新参数路径, 不重复原契约。

覆盖维度:
- _normalize_min_diff_bytes: 16 个输入异常分支 (None / bool / 负数 / 0 / 上界 / float / str / list / dict / object)
- _commit_result: head 透传 + 键集不变量
- TypedDict shape + 模块常量 + 接口不回归
"""
from __future__ import annotations

import pytest

from xragent.tools import git_tools
from xragent.tools.git_tools import (
    DEFAULT_MIN_DIFF_BYTES,
    MIN_DIFF_BYTES_UPPER_BOUND,
    GitCommitResult,
    _commit_result,
    _normalize_min_diff_bytes,
)


# ============================================================================
# _normalize_min_diff_bytes — 纯函数边界
# ============================================================================


def test_normalize_none_returns_default():
    """None 走兜底: Agent 不传参数等价于不设门槛。"""
    assert _normalize_min_diff_bytes(None) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_default_passes_through():
    """直接传 default 值 → 原值返回。"""
    assert _normalize_min_diff_bytes(DEFAULT_MIN_DIFF_BYTES) == 0


def test_normalize_positive_int_passes_through():
    """合法正整数透传。"""
    assert _normalize_min_diff_bytes(100) == 100


def test_normalize_exact_upper_bound_returns_upper_bound():
    """等於上限时不被 clamp 掉。"""
    assert _normalize_min_diff_bytes(MIN_DIFF_BYTES_UPPER_BOUND) == MIN_DIFF_BYTES_UPPER_BOUND


def test_normalize_large_int_clamps_to_upper_bound():
    """巨大数 clamp 到上界 (防 git diff --shortstat 挂死)。"""
    huge = MIN_DIFF_BYTES_UPPER_BOUND * 100
    assert _normalize_min_diff_bytes(huge) == MIN_DIFF_BYTES_UPPER_BOUND


def test_normalize_over_upper_boundary_clamps():
    """上界 + 1 → 上界。"""
    assert _normalize_min_diff_bytes(MIN_DIFF_BYTES_UPPER_BOUND + 1) == MIN_DIFF_BYTES_UPPER_BOUND


def test_normalize_zero_int_returns_default():
    """0 → default (虽然 0 == default, 但走的是 <=0 分支, 不是透传)。"""
    assert _normalize_min_diff_bytes(0) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_negative_int_returns_default():
    """负数 → default (Agent 不应能传负门槛)。"""
    assert _normalize_min_diff_bytes(-100) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_negative_one_returns_default():
    """-1 是边界值, 应归 default。"""
    assert _normalize_min_diff_bytes(-1) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_bool_true_returns_default():
    """bool 是 int 子类, True 会被 isinstance(int) 命中 → 必须先排除。"""
    assert _normalize_min_diff_bytes(True) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_bool_false_returns_default():
    """False 同上 (False 也会被 isinstance(int) 命中)。"""
    assert _normalize_min_diff_bytes(False) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_float_positive_truncates_to_int():
    """float(3.7) → int(3.7) = 3 (截断, 不是四舍五入)。"""
    assert _normalize_min_diff_bytes(3.7) == 3


def test_normalize_float_above_one_truncates():
    """float(99.9) → 99。"""
    assert _normalize_min_diff_bytes(99.9) == 99


def test_normalize_float_at_upper_bound_truncates_to_upper_bound():
    """float(上界) → 上界。"""
    assert _normalize_min_diff_bytes(float(MIN_DIFF_BYTES_UPPER_BOUND)) == MIN_DIFF_BYTES_UPPER_BOUND


def test_normalize_float_negative_returns_default():
    """负 float → default。"""
    assert _normalize_min_diff_bytes(-1.5) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_string_numeric_passes_through():
    """\"100\" 强转成功 → 100。"""
    assert _normalize_min_diff_bytes("100") == 100


def test_normalize_string_negative_returns_default():
    """\"-5\" 强转后 ≤0 → default。"""
    assert _normalize_min_diff_bytes("-5") == DEFAULT_MIN_DIFF_BYTES


def test_normalize_string_non_numeric_returns_default():
    """\"abc\" 不可转 int → default。"""
    assert _normalize_min_diff_bytes("abc") == DEFAULT_MIN_DIFF_BYTES


def test_normalize_string_with_whitespace_returns_default():
    """\"  \" 强转失败 → default。"""
    assert _normalize_min_diff_bytes("  ") == DEFAULT_MIN_DIFF_BYTES


def test_normalize_empty_string_returns_default():
    """\"\" 强转失败 → default。"""
    assert _normalize_min_diff_bytes("") == DEFAULT_MIN_DIFF_BYTES


def test_normalize_list_returns_default():
    """list 不可转 int → default。"""
    assert _normalize_min_diff_bytes([1, 2, 3]) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_dict_returns_default():
    """dict 不可转 int → default。"""
    assert _normalize_min_diff_bytes({"x": 1}) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_object_returns_default():
    """自定义对象 (不是 str/int) → default。"""

    class NotANumber:
        pass

    assert _normalize_min_diff_bytes(NotANumber()) == DEFAULT_MIN_DIFF_BYTES


def test_normalize_custom_default_is_respected():
    """kwargs default 可被覆盖 (供未来调三方 helper 复用)。"""
    assert _normalize_min_diff_bytes(None, default=42) == 42
    assert _normalize_min_diff_bytes(-1, default=42) == 42
    assert _normalize_min_diff_bytes(99, default=42) == 99


# ============================================================================
# _commit_result — 工厂函数
# ============================================================================


def test_commit_result_with_sha_head():
    """成功 commit: head 是 sha → no_changes=False。"""
    r = _commit_result("abc1234567")
    assert r == {"ok": True, "head": "abc1234567", "no_changes": False}


def test_commit_result_with_none_head():
    """无改动: head=None → no_changes=True (幂等)。"""
    r = _commit_result(None)
    assert r == {"ok": True, "head": None, "no_changes": True}


def test_commit_result_keys_exactly_three():
    """严格 3 键 (与 LLM 契约对齐, test_git_tools.py 也锁这个)。"""
    r = _commit_result("sha")
    assert set(r.keys()) == {"ok", "head", "no_changes"}
    assert len(r) == 3


def test_commit_result_keys_stable_for_none():
    """即使是 no_changes 分支也保持 3 键。"""
    r = _commit_result(None)
    assert set(r.keys()) == {"ok", "head", "no_changes"}


def test_commit_result_ok_always_true():
    """ok 恒为 True (失败分支由 SideGit 之外的 caller 自处理)。"""
    assert _commit_result("sha")["ok"] is True
    assert _commit_result(None)["ok"] is True


# ============================================================================
# TypedDict 形状契约
# ============================================================================


def test_git_commit_result_typed_dict_has_required_keys():
    """``GitCommitResult`` TypedDict 显式声明 3 个键 (LLM schema 生成依据)。

    注: ``from __future__ import annotations`` 让 ``bool`` 变成 ``ForwardRef``,
    这里用 ``__annotations__`` 的 key 集合锁契约, 不强校验具体类型。
    """
    annotations = GitCommitResult.__annotations__
    assert set(annotations.keys()) == {"ok", "head", "no_changes"}
    # ForwardRef 不可用 ``is bool`` 比较, 至少验证它存在
    assert "ok" in annotations
    assert "head" in annotations
    assert "no_changes" in annotations


# ============================================================================
# 模块常量暴露 (供外部调用方引用)
# ============================================================================


def test_default_min_diff_bytes_is_zero():
    """锁当前默认契约: Agent 不传 min_diff_bytes → 等价于"不设门槛"。"""
    assert DEFAULT_MIN_DIFF_BYTES == 0


def test_min_diff_bytes_upper_bound_is_sane():
    """上界应该足够大允许常用值 (1000 行) 但不至于触发 perf 问题。"""
    assert MIN_DIFF_BYTES_UPPER_BOUND >= 1000
    assert MIN_DIFF_BYTES_UPPER_BOUND <= 10_000_000


# ============================================================================
# git_tools module surface — 接口回归 (避免改 _normalize 时误伤 module attr)
# ============================================================================


def test_git_tools_module_exposes_helpers():
    """白盒: 新 helper 应能从 import 到, 便于其他模块复用。"""
    assert hasattr(git_tools, "_normalize_min_diff_bytes")
    assert hasattr(git_tools, "_commit_result")
    assert hasattr(git_tools, "DEFAULT_MIN_DIFF_BYTES")
    assert hasattr(git_tools, "MIN_DIFF_BYTES_UPPER_BOUND")
    assert hasattr(git_tools, "GitCommitResult")


def test_git_tools_public_signatures_unchanged():
    """git_commit / git_push 公开签名仍兼容 LLM (test_git_tools 锁)。"""
    import inspect

    commit_sig = inspect.signature(git_tools.git_commit)
    assert "message" in commit_sig.parameters
    assert "min_diff_bytes" in commit_sig.parameters  # 新参数 (keyword-only)
    assert commit_sig.parameters["message"].default is inspect.Parameter.empty

    push_sig = inspect.signature(git_tools.git_push)
    assert "remote" in push_sig.parameters
    assert "branch" in push_sig.parameters
    # min_diff_bytes 不应进 git_push 签名
    assert "min_diff_bytes" not in push_sig.parameters
