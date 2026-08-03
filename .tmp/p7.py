#!/usr/bin/env python3.11
"""Part 7: §四 scoring 不变量行更新."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "| scoring/ 目录占位 | `src/xragent/scoring/` v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；v0.3.1 登记预留 v0.4 评分基线（ADR-0012 / ADR-0013 D6）；v0.13.1 重新确认仍未建不删，cleanup 决策留给后续轮次（见 ADR-0017） |"
new = "| scoring/ v0.4 baseline 已 ship | `src/xragent/scoring/__init__.py` (827 B) + `score.py` (~8 KB) 均 git tracked；`score_turn(TurnRecord) -> float` 启发式 + 3 常量 (`SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE`)，ROADMAP v0.4 「每个 turn 加 score 字段」目标落地；commit `8125486d feat(scoring): v0.4 baseline (round 425)` + `a1d51ee2 refactor(scoring)`。注：ROADMAP.md v0.4 节仍写「计划」属 ROADMAP drift，留 ROADMAP 单独 round（见 ADR-0025 D3） |"
assert old in t, "A2 old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("A2/D3 §四 scoring OK")
