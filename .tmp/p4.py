#!/usr/bin/env python3.11
"""Part 4: §二 scoring 段占位 → v0.4 baseline."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "├── scoring/                   # 占位包（v0.13.1 状态：持续仅 __pycache__/，缺 __init__.py，未 git tracked；\n│                             #   v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 v0.4 评分基线；\n│                             #   v0.13.1（ADR-0017）重新确认仍未建不删；ROADMAP 未把 scoring/\n│                             #   提为 blocked，cleanup 决策留给后续轮次）"
new = "├── scoring/                   # v0.4 baseline 已 ship：启发式 score_turn (round 425) + 3 常量 SCORE_ERROR / SCORE_OK_BASE / SCORE_RANGE\n│                             #   __init__.py re-export + score.py 实现（git tracked；commit `8125486d` + `a1d51ee2`）\n│                             #   ROADMAP.md v0.4 节仍写「计划」属 ROADMAP drift，留待 ROADMAP 单独 round（ADR-0025 D3）"
assert old in t, "D3 old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("D3 §二 scoring OK")
