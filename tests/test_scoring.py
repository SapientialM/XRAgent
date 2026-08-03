"""``xragent.scoring.score`` 单测 —— ROADMAP v0.4 基线启发式。

覆盖：
  * 显式失败 (``error`` 非空) → 0.0
  * observation.ok=True → 基础分 + 效率奖励
  * observation.ok=False → 0.2
  * observation 为 None → 0.5
  * wall_ms 慢 → 惩罚
  * tokens_out 多 → 惩罚
  * 总分裁剪到 ``[0.0, 1.0]``
  * 函数是纯函数（不修改 record）
"""
from __future__ import annotations

from dataclasses import replace

from xragent.core.turn import TurnRecord
from xragent.scoring import (
    SCORE_ERROR,
    SCORE_OK_BASE,
    SCORE_RANGE,
    score_turn,
)


def _rec(**overrides):
    """构造一个 ``observation.ok=True / wall_ms=1000`` 的 TurnRecord 默认值。"""
    base = TurnRecord(
        turn_id="t1",
        ts=0.0,
        think="",
        action={"tool": "noop"},
        observation={"ok": True},
        wall_ms=1000,
        tokens_out=100,
    )
    return replace(base, **overrides)


def test_error_short_circuits_to_zero():
    """``error`` 非空 → ``SCORE_ERROR``，其它字段不影响。"""
    rec = _rec(error="boom", observation={"ok": True}, wall_ms=10)
    assert score_turn(rec) == SCORE_ERROR


def test_ok_base_plus_fast_wall_reward():
    """ok=True + wall_ms 极快 → 0.7 基础 + 0.1 奖励 = 0.8"""
    assert score_turn(_rec()) == 0.8


def test_ok_base_slow_wall_penalty():
    """ok=True + wall_ms 极慢 → 0.7 基础 - 0.1 惩罚 = 0.6"""
    rec = _rec(wall_ms=60_000)
    assert score_turn(rec) == 0.6


def test_ok_base_mid_wall_neutral():
    """ok=True + wall_ms 区间内 → 基础 0.7（线性插值在中点正好 0）"""
    # 5_000..30_000 中点是 17_500；wall_ms=17_500 时 delta=0
    rec = _rec(wall_ms=17_500)
    assert score_turn(rec) == 0.7


def test_observation_fail_gets_low_score():
    """``observation["ok"] is False`` → 0.2 基础 + 可能的奖励"""
    rec = _rec(observation={"ok": False})
    # 0.2 + wall=1000(+0.1) = 0.3
    assert score_turn(rec) == 0.3


def test_observation_fail_slow_wall_clipped_to_zero():
    """``observation["ok"] is False`` + wall 极慢 + tokens 重 → 0.2 -0.1 -0.1 = 0"""
    rec = _rec(observation={"ok": False}, wall_ms=60_000, tokens_out=3000)
    assert score_turn(rec) == 0.0


def test_observation_none_is_neutral():
    """``observation`` 缺失 → 0.5 中性"""
    rec = _rec(observation=None)
    # 0.5 + wall=1000(+0.1) = 0.6
    assert score_turn(rec) == 0.6


def test_tokens_out_penalty_applied():
    """``tokens_out > 2000`` → -0.1 惩罚"""
    rec = _rec(tokens_out=3000)
    # 0.7 + 0.1 - 0.1 = 0.7
    assert score_turn(rec) == 0.7


def test_score_is_clipped_to_range():
    """所有返回 ∈ ``SCORE_RANGE``。"""
    # 极端组合：fail + 慢 + 重 → 应该是 0
    rec = _rec(observation={"ok": False}, wall_ms=999_999, tokens_out=999_999)
    score = score_turn(rec)
    lo, hi = SCORE_RANGE
    assert lo <= score <= hi


def test_score_turn_is_pure():
    """函数不修改 record（纯函数契约）。"""
    rec = _rec()
    snap = replace(rec)  # 浅拷贝（dataclass 不深拷，但字段都是不可变）
    _ = score_turn(rec)
    assert rec == snap


def test_score_turn_does_not_recursive_loop():
    """``record.score`` 字段不影响计算（避免"上一轮 score 影响这一轮"）。"""
    # 哪怕传入 score=0.0，函数结果仍按 error/obs/wall/tokens 算
    rec = _rec(score=0.0)
    assert score_turn(rec) == 0.8  # 跟 test_ok_base_plus_fast_wall_reward 一致