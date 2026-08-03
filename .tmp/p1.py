#!/usr/bin/env python3.11
"""Part 1: append ADR-0025 to top ADR list."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "> [ADR-0024](adr/0024-architecture-v0-round-582-actual-doc-landing.md)（v0.13.2 round 582 doc sync：autonomous journal（diary 头部预览 + round_done 留痕）+ autonomous rng 显式参数化（可选）+ tools/web_search.py 5min 限流改造（per-host throttle）；§一 / §三 / §四 / §五 全部 doc 同步落地）。\n"
new = old + "> [ADR-0025](adr/0025-architecture-v0-round-588-drift-scan-5-11-scoring-v0-4-and-snapshot-inspect.md)（round 588 drift 扫描：§一 schema 5.9 → 5.11 + §二 §四 scoring v0.4 baseline + §二 snapshot/inspect.py + §二 memory/manager.py.bak.5.10 + §五补 5 行 —— 仅 doc 同步，未碰 src/）。\n"
assert old in t, "D7 old not found"
assert t.count(old) == 1, "D7 old count != 1"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("D7 OK")
