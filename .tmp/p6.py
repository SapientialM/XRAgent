#!/usr/bin/env python3.11
"""Part 6: §二 memory 段加 manager.py.bak.5.10 + schema 5.9 → 5.11."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "├── memory/manager.py          # MemoryManager：SQLite 长期事实 + compress_if_needed 封装\n│                             # 当前有效 schema 5.9（v0.2.7 +LRU 5.8；v0.5 5.9 二次回填 5.4/5.6 丢失的\n│                             # idx_facts_tags / idx_facts_title + 配套 recent() method），见 ADR-0004 / ADR-0008 / ADR-0014"
new = "├── memory/manager.py          # MemoryManager：SQLite 长期事实 + compress_if_needed 封装\n│                             # 当前有效 schema 5.11（v0.2.7 +LRU 5.8；v0.5 5.9 二次回填 5.4/5.6 丢失的\n│                             # idx_facts_tags / idx_facts_title + 配套 recent() method；\n│                             # v0.5.10 +expires_ts + TTL；v0.5.11 +access_count + LFU）\n│                             # 见 ADR-0004 / ADR-0008 / ADR-0014 / ADR-0025\n├── memory/manager.py.bak.5.10 # 5.10 → 5.11 迁移前的版本快照，git tracked（commit `cb13c186`），不删\n│                             # 与 ADR-0013 D8 已删的 manager.py.bak（无后缀）是不同文件，清理决策留给后续 round（见 ADR-0025 C2）"
assert old in t, "C2 old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("C2 §二 memory OK")
