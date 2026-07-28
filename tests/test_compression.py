"""SimpleCompression + hook registry：之前零覆盖，补齐边界条件。

重点覆盖：
  * approx_tokens 对 None / 缺 content / 空串 / 单 message 的下限
  * should_compress 在预算边界（== / < / >）的判定
  * compress 在空列表 / 纯 system / 纯非 system / 刚好 _KEEP_RECENT / 超 _KEEP_RECENT 的截断行为
  * target_ratio=0、budget_tokens=0 的极值
  * hook.register / hook.get / 重复注册覆盖 / 缺失 KeyError
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from xragent.compression import hook
from xragent.compression.simple import (
    SimpleCompression,
    approx_tokens,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_msg(role: str, content: str = ""):
    """构造一个拥有 .role / .content 的轻量对象。"""
    return SimpleNamespace(role=role, content=content)


def long_text(n_chars: int) -> str:
    """生成 n_chars 个字符的字符串，token ≈ n_chars // 4。"""
    return "x" * n_chars


# ---------------------------------------------------------------------------
# approx_tokens
# ---------------------------------------------------------------------------

def test_approx_tokens_empty_list_returns_zero():
    """空列表应有 0 token，不应抛异常。"""
    assert approx_tokens([]) == 0


def test_approx_tokens_message_with_none_content():
    """content=None 应被 'or ""' 兜底；当字符串后仍走 max(1, len//4) 下限 1。"""
    msgs = [make_msg("user", None)]  # type: ignore[arg-type]
    assert approx_tokens(msgs) == 1


def test_approx_tokens_message_without_content_attribute():
    """缺 content 属性 → getattr 默认值 "" → 仍按下限计 1。"""
    msgs = [SimpleNamespace(role="user")]  # no .content at all
    assert approx_tokens(msgs) == 1


def test_approx_tokens_empty_string_still_counts_one():
    """空字符串也走 max(1, 0//4) = 1，避免出现"空消息不算 token"的诡异空隙。"""
    msgs = [make_msg("user", "")]
    assert approx_tokens(msgs) == 1


def test_approx_tokens_single_long_message():
    """n_chars//4 的近似估算；80 chars → 20 tokens。"""
    msgs = [make_msg("assistant", long_text(80))]
    assert approx_tokens(msgs) == 80 // 4


def test_approx_tokens_sums_across_messages():
    """多个 message 的 token 应累加。"""
    msgs = [make_msg("user", "abcd"), make_msg("assistant", "abcdefgh")]
    assert approx_tokens(msgs) == 1 + 2


# ---------------------------------------------------------------------------
# should_compress
# ---------------------------------------------------------------------------

def test_should_compress_below_budget():
    c = SimpleCompression(budget_tokens=10)
    msgs = [make_msg("user", "abc")]  # 1 token
    assert c.should_compress(msgs) is False


def test_should_compress_exact_budget_is_not_over():
    """边界：== budget 不算超，should_compress 必须返回 False。"""
    c = SimpleCompression(budget_tokens=4)
    msgs = [make_msg("user", long_text(16))]  # 16//4 = 4 tokens == budget
    assert approx_tokens(msgs) == 4
    assert c.should_compress(msgs) is False


def test_should_compress_just_over_budget():
    """边界：== budget + 1 → 必压缩。"""
    c = SimpleCompression(budget_tokens=4)
    msgs = [make_msg("user", long_text(20))]  # 5 tokens > 4
    assert c.should_compress(msgs) is True


# ---------------------------------------------------------------------------
# compress：未触发压缩时
# ---------------------------------------------------------------------------

def test_compress_returns_same_list_when_under_budget():
    """should_compress=False 时 compress 应原样返回（同一对象）。"""
    c = SimpleCompression(budget_tokens=1000)
    msgs = [make_msg("system", "you are a helper"), make_msg("user", "hi")]
    assert c.should_compress(msgs) is False
    assert c.compress(msgs) is msgs


def test_compress_empty_list_stays_empty():
    """空列表 token=0，远小于预算，compress 返回 []。"""
    c = SimpleCompression(budget_tokens=10)
    out = c.compress([])
    assert out == []
    assert c.should_compress([]) is False


# ---------------------------------------------------------------------------
# compress：触发压缩时 — system / non-system 切片逻辑
# ---------------------------------------------------------------------------

def test_compress_keeps_only_first_system_when_many():
    """_RESERVED_SYSTEM = 1：即便有 3 条 system，也只留第一条。"""
    c = SimpleCompression(budget_tokens=1)  # 几乎任何内容都触发
    msgs = [
        make_msg("system", "sys-A"),
        make_msg("system", "sys-B"),
        make_msg("system", "sys-C"),
        make_msg("user", long_text(40)),  # 10 tokens
        make_msg("assistant", long_text(40)),  # 10 tokens
    ]
    out = c.compress(msgs)
    assert c.should_compress(msgs) is True
    system_msgs = [m for m in out if m.role == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0].content == "sys-A"


def test_compress_with_all_system_messages_drops_to_one():
    """全部是 system：non_system 为空 → 仅保留第一条 system。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = [make_msg("system", f"sys-{i}") for i in range(5)]
    out = c.compress(msgs)
    assert len(out) == 1
    assert out[0].role == "system"
    assert out[0].content == "sys-0"


def test_compress_with_no_system_messages_starts_with_tail():
    """没有 system 时：结果 = non_system[-_KEEP_RECENT:]。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = [make_msg("user", f"u-{i}") for i in range(10)]
    out = c.compress(msgs)
    assert len(out) == SimpleCompression.__init__.__defaults__  # 占位，保证 linter 不报

    # 实际断言：非 system 应取最后 6 条
    # 直接验证内容而不依赖未导出常量：
    assert [m.content for m in out] == [f"u-{i}" for i in range(4, 10)]


def test_compress_exactly_keep_recent_does_not_drop():
    """非 system 数量刚好等于 _KEEP_RECENT → 不丢任何。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = [make_msg("user", long_text(40)) for _ in range(6)]
    out = c.compress(msgs)
    assert len(out) == 6
    assert all(m.role == "user" for m in out)


def test_compress_drops_earliest_when_over_keep_recent():
    """非 system 数量 > _KEEP_RECENT → 丢最早的。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = [make_msg("user", long_text(40)) for _ in range(10)]
    out = c.compress(msgs)
    # 应只保留后 6 条
    assert len(out) == 6


def test_compress_preserves_role_ordering_in_tail():
    """末尾切片保持原顺序：最后 6 条非 system 的相对顺序必须不变。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = []
    for i in range(8):
        msgs.append(make_msg("user", f"u-{i}"))
        msgs.append(make_msg("assistant", f"a-{i}"))
    out = c.compress(msgs)
    # 一共 16 条非 system，最后 6 条即 (u-5, a-5, u-6, a-6, u-7, a-7)
    pairs = [(m.role, m.content) for m in out]
    assert pairs == [
        ("user", "u-5"),
        ("assistant", "a-5"),
        ("user", "u-6"),
        ("assistant", "a-6"),
        ("user", "u-7"),
        ("assistant", "a-7"),
    ]


def test_compress_with_mixed_system_prefix_then_tail():
    """system 在最前 + 长串 user → 结果 = [system] + last-6-user。"""
    c = SimpleCompression(budget_tokens=1)
    msgs = [make_msg("system", "you are helper")]
    msgs.extend(make_msg("user", long_text(40)) for _ in range(8))
    out = c.compress(msgs)
    assert out[0].role == "system" and out[0].content == "you are helper"
    assert len(out) == 1 + 6
    assert all(m.role == "user" for m in out[1:])


# ---------------------------------------------------------------------------
# compress：构造参数边界
# ---------------------------------------------------------------------------

def test_compress_target_ratio_zero_does_not_break():
    """target_ratio=0 让 target=0，但代码只用 budget 判断 → 不应崩。"""
    c = SimpleCompression(budget_tokens=4, target_ratio=0.0)
    msgs = [make_msg("user", long_text(20))]  # 5 tokens > 4
    out = c.compress(msgs)
    assert len(out) == 1
    assert c.target == 0  # 真的算出 0


def test_compress_budget_zero_always_triggers():
    """budget=0：任何消息都满足 >0 → 永远压缩。"""
    c = SimpleCompression(budget_tokens=0)
    msgs = [make_msg("user", "hi")]
    assert c.should_compress(msgs) is True
    out = c.compress(msgs)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# hook registry
# ---------------------------------------------------------------------------

def test_hook_get_returns_registered_class():
    """默认注册了 'simple'，且返回值可调用（实例化）。"""
    cls = hook.get("simple")
    assert cls is SimpleCompression
    assert isinstance(cls(budget_tokens=10), SimpleCompression)


def test_hook_register_overrides_existing_name():
    """同名注册允许覆盖（dict 语义）。"""

    class FakeCompression:
        pass

    hook.register("simple", FakeCompression)
    try:
        assert hook.get("simple") is FakeCompression
    finally:
        # 还原成 SimpleCompression，避免污染其他测试
        hook.register("simple", SimpleCompression)


def test_hook_get_unknown_name_raises_keyerror():
    """未注册的 name → KeyError（不是 ValueError / IndexError）。"""
    with pytest.raises(KeyError):
        hook.get("definitely-not-registered-zzz")