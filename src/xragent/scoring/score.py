"""turn score 启发式 —— :func:`score_turn`。

## 为什么需要

:class:`~xragent.core.turn.TurnRecord` 自带 ``score: float | None`` 字段但
没有默认填充函数。ROADMAP v0.4 写明：

  > 每个 turn 加 ``score`` 字段（默认 ``None``；测试通过率作为基线）
  > N 轮无 score 提升 → 自动进入"长眠"

本函数是 v0.4 的最小入口：一个**纯函数**、**可单测**、**只看 record
本身**的启发式。它**不**调用 LLM、不读文件、不写持久化；调用方拿分后
自行决定是否 ``record.score = score_turn(record)``。

后续 v0.4.x 可以让 :class:`xragent.autonomous.Autonomous` 在每个 turn
结束后把 ``score`` 写到 jsonl，并在 N 轮无提升时触发"长眠"。但那是
上层 wiring，本模块保持纯函数 + 字段契约。

## 启发式评分契约

score ∈ ``SCORE_RANGE`` = ``[0.0, 1.0]``，越大越好。

| 情况                                        | 分值    |
|---------------------------------------------|---------|
| ``record.error`` 非空                       | ``SCORE_ERROR`` (0.0) — 显式失败直接归零 |
| ``record.observation`` 为 ``None``           | 0.5 — 没拿到结果，视为部分成功 |
| ``observation["ok"] is True``               | ``SCORE_OK_BASE`` (0.7) 基础 |
| ``observation["ok"] is False``              | 0.2 — 工具报告失败 |

基础上叠加两个**效率奖励/惩罚**（v0.4 基线，文档化便于后续调参）：

  * **wall_ms 奖励**：``wall_ms < 5_000`` → +0.1；``wall_ms >= 30_000`` → -0.1。
    区间内线性插值。Agent 应"快且正确"，不是"快但错"。
  * **tokens 惩罚**：``tokens_out > 2_000`` → -0.1（鼓励简洁）。

最后裁剪到 ``[0.0, 1.0]``，避免堆叠奖励越界。

## 设计取舍

1. **不用 LLM**：score 必须确定性，否则"N 轮无提升"判定变噪声。
2. **只看 record 字段**：便于 mock / 单测，不引入隐藏 IO。
3. **常量集中**：``SCORE_OK_BASE`` / ``SCORE_ERROR`` / ``SCORE_RANGE`` 都
   暴露在 :mod:`xragent.scoring` 顶层，方便上层（如 watchdog / 长眠判定）
   直接引用而**不**绑死数值。
4. **不修改 record**：纯函数；调用方选择时机。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ..core.turn import TurnRecord


# ---- 评分常量（公开，便于上层 watchdog / 长眠判定复用） --------------------

SCORE_RANGE: Final[tuple[float, float]] = (0.0, 1.0)
"""score 取值范围 ``[min, max]``。"""

SCORE_ERROR: Final[float] = 0.0
"""``record.error`` 非空时的硬截断分 —— 显式失败直接归零。"""

SCORE_OK_BASE: Final[float] = 0.7
"""``observation["ok"] is True`` 的基础分。"""

SCORE_NO_OBSERVATION: Final[float] = 0.5
"""``observation`` 为 ``None``（即该 turn 没产生工具调用结果）的中间分。"""

SCORE_OBSERVATION_FAIL: Final[float] = 0.2
"""``observation["ok"] is False`` 时的失败分。"""

# ---- 效率奖励/惩罚阈值 ------------------------------------------------------

_WALL_MS_FAST: Final[int] = 5_000
"""``wall_ms`` 快于此值给 ``+0.1`` 奖励。"""

_WALL_MS_SLOW: Final[int] = 30_000
"""``wall_ms`` 慢于此值给 ``-0.1`` 惩罚。"""

_TOKENS_OUT_HEAVY: Final[int] = 2_000
"""``tokens_out`` 超过此值给 ``-0.1`` 惩罚（鼓励简洁）。"""


def _wall_ms_delta(wall_ms: int) -> float:
    """``wall_ms`` 维度的奖励/惩罚（区间线性插值）。

    行为：

      * ``wall_ms <= _WALL_MS_FAST`` → ``+0.1``
      * ``wall_ms >= _WALL_MS_SLOW`` → ``-0.1``
      * 中间区间 → 从 ``+0.1`` 线性衰减到 ``-0.1``，过 ``(_WALL_MS_FAST + _WALL_MS_SLOW) / 2``
        时正好 ``0``。
    """
    if wall_ms <= _WALL_MS_FAST:
        return 0.1
    if wall_ms >= _WALL_MS_SLOW:
        return -0.1
    # 中间区间：从 +0.1 到 -0.1 线性
    span = _WALL_MS_SLOW - _WALL_MS_FAST
    progress = (wall_ms - _WALL_MS_FAST) / span  # 0..1
    return 0.1 + (-0.1 - 0.1) * progress  # 0.1 → -0.1


def _clip(score: float) -> float:
    """裁剪到 :data:`SCORE_RANGE` 并保留 4 位小数（浮点稳定性 + 易读）。"""
    lo, hi = SCORE_RANGE
    return round(max(lo, min(hi, score)), 4)


def score_turn(record: "TurnRecord") -> float:
    """给一个 ``TurnRecord`` 算启发式分（ROADMAP v0.4 基线启发式）。

    契约：

      * 返回值 ∈ ``[0.0, 1.0]``；
      * 显式失败 (``record.error`` 非空) → ``SCORE_ERROR`` (0.0)；
      * 否则按 :mod:`xragent.scoring.score` 顶部表格叠加 wall_ms / tokens 奖励。

    Args:
        record: 一个 :class:`~xragent.core.turn.TurnRecord` 实例。函数只读
            ``error`` / ``observation`` / ``wall_ms`` / ``tokens_out`` 四个
            字段；其它字段（``think`` / ``action`` / ``tokens_in`` /
            ``score``）不影响分。

    Returns:
        float: 0.0..1.0 之间的小数。保留 4 位小数，避免浮点尾巴污染 jsonl。

    Examples:
        >>> from xragent.core.turn import TurnRecord
        >>> rec = TurnRecord(turn_id="t1", ts=0.0, think="",
        ...                  action={"tool": "noop"},
        ...                  observation={"ok": True},
        ...                  wall_ms=2000, tokens_out=100)
        >>> 0.7 <= score_turn(rec) <= 0.9  # 0.7 基础 + 0.1 快奖励
        True
        >>> rec_err = TurnRecord(turn_id="t2", ts=0.0, think="",
        ...                      action=None, observation=None,
        ...                      error="boom")
        >>> score_turn(rec_err)
        0.0
    """
    # 1) 显式失败 → 硬截断
    if record.error:
        return SCORE_ERROR

    # 2) 基础分
    obs = record.observation
    if obs is None:
        base: float = SCORE_NO_OBSERVATION
    else:
        ok = obs.get("ok")
        if ok is True:
            base = SCORE_OK_BASE
        elif ok is False:
            base = SCORE_OBSERVATION_FAIL
        else:
            # observation 存在但没有 "ok" 键（罕见的半结构化 obs）→ 中性分
            base = SCORE_NO_OBSERVATION

    # 3) 效率维度叠加
    score = base + _wall_ms_delta(int(record.wall_ms))
    if record.tokens_out > _TOKENS_OUT_HEAVY:
        score -= 0.1

    # 4) 裁剪 + 浮点稳定
    return _clip(score)


__all__ = [
    "SCORE_RANGE",
    "SCORE_ERROR",
    "SCORE_OK_BASE",
    "SCORE_NO_OBSERVATION",
    "SCORE_OBSERVATION_FAIL",
    "score_turn",
]