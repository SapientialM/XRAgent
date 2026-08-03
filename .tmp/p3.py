#!/usr/bin/env python3.11
"""Part 3: util/ 8 → 9 + print_guard."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "  当前 **8 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n  `heartbeat` / `http_parents` / `web_search_rl`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；\n  v0.2.8 +http_parents，见 ADR-0009；v0.13.2 +web_search_rl，见 ADR-0024）。"
new = "  当前 **9 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n  `heartbeat` / `http_parents` / `web_search_rl` / `print_guard`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；\n  v0.2.7 +heartbeat，见 ADR-0008；v0.2.8 +http_parents，见 ADR-0009；v0.10 +print_guard，见 ADR-0018；\n  v0.13.2 +web_search_rl，见 ADR-0024）。"
assert old in t, "D2-util old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("D2-util OK")
