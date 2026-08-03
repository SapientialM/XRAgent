#!/usr/bin/env python3.11
"""Part 2: §一 记忆行 schema 5.9 → 5.11."""
from pathlib import Path
p = Path("docs/architecture-v0.md")
t = p.read_text(encoding="utf-8")
old = "| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>+ `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）<br>+ `snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，与 `count_cleanup.py` 对称，见 ADR-0019）<br>`memory/manager.py` 当前有效 schema **5.9**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建），基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见 ADR-0014<br>注：常量 `SCHEMA_VERSION = 58` 未 bump 是已知遗留（5.9 migration 是 DDL-only 的二次回填，不改字段），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准 |"
new = "| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>+ `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）<br>+ `snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，与 `count_cleanup.py` 对称，见 ADR-0019）<br>+ `snapshot/inspect.py`（round 421 tag 检视工具，与 `_tag_index` 共享原语，见 ADR-0025）<br>`memory/manager.py` 当前有效 schema **5.11**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建 + **5.10 `expires_ts` + TTL 索引 + `recall_unexpired` / `purge_expired` / `set_ttl`** + **5.11 `access_count` + `idx_facts_access_count_ts` + `recall_most_accessed` / `recall_least_accessed` / `increment_access_count` LFU**），基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见 ADR-0014，5.10 TTL + 5.11 LFU 见 ADR-0025<br>注：`SCHEMA_VERSION = 511`（5.11 已 bump；与 ADR-0014 当时记录的「`SCHEMA_VERSION = 58` 未 bump 是已知遗留」已不一致 —— 5.9 → 5.11 期间 DDL 多次回填 + `access_count` 字段新增是触发 bump 的真因，见 ADR-0025 A1） |"
assert old in t, "D2 old not found"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("D2 §一 OK")
