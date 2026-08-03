#!/usr/bin/env python3.11
"""Part 5: §二 snapshot 段加 inspect.py."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "├── snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)\n│                             #          时间清理 standalone 镜像（与 count_cleanup 对称），走 _tag_index helper\n│                             #          commit `fbe16191`，见 ADR-0019；side_git.py 旧 inline wrapper 保留"
new = "├── snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)\n│                             #          时间清理 standalone 镜像（与 count_cleanup 对称），走 _tag_index helper\n│                             #          commit `fbe16191`，见 ADR-0019；side_git.py 旧 inline wrapper 保留\n├── snapshot/inspect.py        # round 421: snapshot tag 检视工具（与 `_tag_index` 共享原语），见 ADR-0025"
assert old in t, "D4 old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("D4 §二 snapshot OK")
