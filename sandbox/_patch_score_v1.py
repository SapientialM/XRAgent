#!/usr/bin/env python3.11
"""Apply score.py refactor patches via unique-anchor str.replace.

Patches (4 处, 全部用 anchor str.replace + assert count==1 守门):
  P1) 在 _TOKENS_OUT_HEAVY 块后追加 _DELTA_FAST / _DELTA_SLOW 常量
  P2) 重写 _wall_ms_delta 函数体, 把 0.1 / -0.1 / 0.2 magic number 换成常量
  P3) 在 _clip 之前插入 _tokens_out_delta helper
  P4) score_turn 主体把 if record.tokens_out > _TOKENS_OUT_HEAVY: score -= 0.1
       替换成 + _tokens_out_delta(...) 加项

写错任何 anchor 时立即 raise, 不污染原文件。
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("src/xragent/scoring/score.py")
ORIGINAL = TARGET.read_text(encoding="utf-8")
src = ORIGINAL


# ---- P1: 在 _TOKENS_OUT_HEAVY 块后追加 _DELTA_FAST / _DELTA_SLOW 常量 ---------

P1_OLD = '''_TOKENS_OUT_HEAVY: Final[int] = 2_000
"""``tokens_out`` 超过此值给 ``-0.1`` 惩罚（鼓励简洁）。"""


def _wall_ms_delta(wall_ms: int) -> float:'''

P1_NEW = '''_TOKENS_OUT_HEAVY: Final[int] = 2_000
"""``tokens_out`` 超过此值给 ``_DELTA_SLOW`` ( -0.1 ) 惩罚（鼓励简洁）。"""

_DELTA_FAST: Final[float] = 0.1
"""效率维度正向奖励幅度 —— wall_ms 极快时的奖励值。"""

_DELTA_SLOW: Final[float] = -0.1
"""效率维度负向惩罚幅度 —— wall_ms 极慢 / tokens_out 过重时的惩罚值。"""


def _wall_ms_delta(wall_ms: int) -> float:'''

assert src.count(P1_OLD) == 1, f"P1 anchor not unique: {src.count(P1_OLD)}"
src = src.replace(P1_OLD, P1_NEW)


# ---- P2: _wall_ms_delta 函数体重写, magic number 换常量 -----------------------

P2_OLD = '''    if wall_ms <= _WALL_MS_FAST:
        return 0.1
    if wall_ms >= _WALL_MS_SLOW:
        return -0.1
    # 中间线性插值（0.1 → -0.1）：t=0 时 +0.1，t=1 时 -0.1；
    # ``0.1 - 0.2 * t`` 比 ``0.1 + (-0.1 - 0.1) * t`` 少一个 magic number，
    # 跨过 t=0.5（中点）时刚好归零。
    t = (wall_ms - _WALL_MS_FAST) / (_WALL_MS_SLOW - _WALL_MS_FAST)
    return 0.1 - 0.2 * t'''

P2_NEW = '''    if wall_ms <= _WALL_MS_FAST:
        return _DELTA_FAST
    if wall_ms >= _WALL_MS_SLOW:
        return _DELTA_SLOW
    # 中间线性插值: 从 _DELTA_FAST 线性过渡到 _DELTA_SLOW。
    # 写 ``_DELTA_FAST + (_DELTA_SLOW - _DELTA_FAST) * t`` 而非
    # ``_DELTA_FAST - 0.2 * t`` —— 后者把 (0.1 - (-0.1)) 这个隐含常量
    # 写死成 0.2, 调参 _DELTA_FAST/_DELTA_SLOW 时容易漏改。
    # 跨过 t=0.5（中点）时, 因为 _DELTA_FAST 和 _DELTA_SLOW 互为相反数,
    # 代数和正好 0。
    t = (wall_ms - _WALL_MS_FAST) / (_WALL_MS_SLOW - _WALL_MS_FAST)
    return _DELTA_FAST + (_DELTA_SLOW - _DELTA_FAST) * t'''

assert src.count(P2_OLD) == 1, f"P2 anchor not unique: {src.count(P2_OLD)}"
src = src.replace(P2_OLD, P2_NEW)


# ---- P3: 在 _clip 之前插入 _tokens_out_delta helper --------------------------

P3_OLD = '''def _clip(score: float) -> float:'''

P3_NEW = '''def _tokens_out_delta(tokens_out: int) -> float:
    """``tokens_out`` 维度的惩罚（鼓励简洁）。

    行为:

      * ``tokens_out > _TOKENS_OUT_HEAVY`` → ``_DELTA_SLOW`` ( -0.1 )
      * 否则 → ``0.0``

    抽此 helper 的两个原因:

      1. 与 :func:`_wall_ms_delta` 对称 —— ``score_turn`` 主流程里
         ``score = base + _wall_ms_delta(...) + _tokens_out_delta(...)``
         一行线性, 三个加项各自独立、好测、好换实现。
      2. 把"超阈值 → 罚"语义封进 helper, ``score_turn`` 不再夹一行
         ``if record.tokens_out > _TOKENS_OUT_HEAVY: score -= 0.1``,
         控制流平直 (round 423 风格: any() 折 if-else / 抽 helper 平流)。
    """
    if tokens_out > _TOKENS_OUT_HEAVY:
        return _DELTA_SLOW
    return 0.0


def _clip(score: float) -> float:'''

assert src.count(P3_OLD) == 1, f"P3 anchor not unique: {src.count(P3_OLD)}"
src = src.replace(P3_OLD, P3_NEW)


# ---- P4: score_turn 主体: tokens_out 改走 helper --------------------------------

P4_OLD = '''    # 3) 效率维度叠加
    score = base + _wall_ms_delta(int(record.wall_ms))
    if record.tokens_out > _TOKENS_OUT_HEAVY:
        score -= 0.1

    # 4) 裁剪 + 浮点稳定'''

P4_NEW = '''    # 3) 效率维度叠加: wall_ms + tokens_out 各自走 helper, 主流程只剩加法。
    score = (
        base
        + _wall_ms_delta(int(record.wall_ms))
        + _tokens_out_delta(int(record.tokens_out))
    )

    # 4) 裁剪 + 浮点稳定'''

assert src.count(P4_OLD) == 1, f"P4 anchor not unique: {src.count(P4_OLD)}"
src = src.replace(P4_OLD, P4_NEW)


# ---- 写回 ----------------------------------------------------------------------

TARGET.write_text(src, encoding="utf-8")
print(f"OK: {len(ORIGINAL)} -> {len(src)} bytes, +{len(src) - len(ORIGINAL)}")
print(f"P1/P2/P3/P4 全部 anchor 命中 (count==1)")