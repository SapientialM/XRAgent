"""turn score 启发式评分（ROADMAP v0.4 起步）。

## 为什么

:class:`~xragent.core.turn.TurnRecord` 早就有 ``score: float | None = None``
字段（与 ``error`` / ``tokens_in`` / ``tokens_out`` 同级），但**没有任何函数
给 score 填值**。ROADMAP v0.4 的目标是:

  > 每个 turn 加 ``score`` 字段（默认 ``None``；测试通过率作为基线）
  > N 轮无 score 提升 → 自动进入"长眠"

v0.4 第一步只需要"一个可解释的启发式"，让 score 从空值变为有意义的标量。
本包提供的 :func:`~xragent.scoring.score.score_turn` 就是 v0.4 的最小入口。

## API

- :func:`~xragent.scoring.score.score_turn` —— 给一个 ``TurnRecord`` 算启发式分。
  详见模块 docstring。
- 评分常量 :data:`SCORE_RANGE` / :data:`SCORE_ERROR` / :data:`SCORE_OK_BASE` /
  :data:`SCORE_NO_OBSERVATION` / :data:`SCORE_OBSERVATION_FAIL` —— 全部 5 个
  公开常量在本顶层 re-export，方便上层 watchdog / 长眠判定 import 而不必
  走 ``from xragent.scoring.score import ...`` 的深层路径（deep import 与
  模块重命名风险耦合）。

## 边界

- 本包**不**改 TurnRecord 字段、不写持久化；调用方拿分后自行决定是否
  ``record.score = score_turn(record)``。
- 不引 LLM 依赖、不查文件系统；纯函数，便于单测。
"""
from __future__ import annotations

from .score import (
    SCORE_ERROR,
    SCORE_NO_OBSERVATION,
    SCORE_OK_BASE,
    SCORE_OBSERVATION_FAIL,
    SCORE_RANGE,
    score_turn,
)

__all__ = [
    "SCORE_ERROR",
    "SCORE_NO_OBSERVATION",
    "SCORE_OK_BASE",
    "SCORE_OBSERVATION_FAIL",
    "SCORE_RANGE",
    "score_turn",
]
