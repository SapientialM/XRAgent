#!/usr/bin/env python3.11
"""Apply ADR-0025 drift fixes to docs/architecture-v0.md - part 1 (8 patches)."""
import sys
from pathlib import Path

path = Path("docs/architecture-v0.md")
text = path.read_text(encoding="utf-8")

def patch(label: str, old: str, new: str, count: int = 1) -> None:
    global text
    if old not in text:
        print(f"FATAL: {label}: old block not found", file=sys.stderr)
        sys.exit(2)
    occurrences = text.count(old)
    if occurrences != count:
        print(f"FATAL: {label}: expected {count}, found {occurrences}", file=sys.stderr)
        sys.exit(2)
    text = text.replace(old, new, count)
    print(f"OK   : {label} ({count}x)")

# D7
patch(
    "D7 top ADR list",
    "> [ADR-0024](adr/0024-architecture-v0-round-582-actual-doc-landing.md)（v0.13.2 round 582 doc sync：autonomous journal（diary 头部预览 + round_done 留痕）+ autonomous rng 显式参数化（可选）+ tools/web_search.py 5min 限流改造（per-host throttle）；§一 / §三 / §四 / §五 全部 doc 同步落地）。\n",
    "> [ADR-0024](adr/0024-architecture-v0-round-582-actual-doc-landing.md)（v0.13.2 round 582 doc sync：autonomous journal（diary 头部预览 + round_done 留痕）+ autonomous rng 显式参数化（可选）+ tools/web_search.py 5min 限流改造（per-host throttle）；§一 / §三 / §四 / §五 全部 doc 同步落地）。\n> [ADR-0025](adr/0025-architecture-v0-round-588-drift-scan-5-11-scoring-v0-4-and-snapshot-inspect.md)（round 588 drift 扫描：§一 schema 5.9 → 5.11（含 5.10 TTL / 5.11 LFU 增量；`SCHEMA_VERSION` 511 已 bump）+ §二 §四 scoring/ 「占位」→「v0.4 baseline 已 ship」 + §二 snapshot/inspect.py 模块描述 + §二 memory/manager.py.bak.5.10 备注 + §五版本对照表补 v0.4 / v0.5.10 / v0.5.11 / v0.10 print_guard 增量 / snapshot/inspect (round 421) 共 5 行 —— 仅 doc 同步，未碰 src/）。\n",
)

# D2 memory row
patch(
    "D2 §一 记忆行 schema 5.11",
    "\u2502 \u8bb0\u5fc6 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`\uff08v0.2+ \u542b cleanup \u5165\u53e3\uff0c\u89c1 ADR-0003\uff09<br>+ `snapshot/_tag_index.py`\uff08v0.5.x \u5171\u4eab\u539f\u8bed\uff0c\u89c1 ADR-0016\uff09+ `snapshot/count_cleanup.py`\uff08v0.11 \u6570\u91cf\u5151\u5e95\uff0c\u89c1 ADR-0016\uff09<br>+ `snapshot/age_cleanup.py`\uff08v0.11+ \u65f6\u95f4\u6e05\u7406 standalone \u955c\u50cf\uff0c\u4e0e `count_cleanup.py` \u5bf9\u79f0\uff0c\u89c1 ADR-0019\uff09<br>`memory/manager.py` \u5f53\u524d\u6709\u6548 schema **5.9**\uff085.0 \u57fa\u7ebf + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`\uff08v0.5 5.9 \u4e8c\u6b21\u56de\u586b\uff09+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` \u91cd\u5efa + 5.4 `idx_facts_tags` \u91cd\u5efa\uff09\uff0c\u57fa\u7ebf\u89c1 ADR-0004\uff0c5.8 LRU \u589e\u91cf\u89c1 ADR-0008\uff0c5.9 \u7d22\u5f15\u56de\u586b\u89c1 ADR-0014<br>\u6ce8\uff1a\u5e38\u91cf `SCHEMA_VERSION = 58` \u672a bump \u662f\u5df2\u77e5\u9057\u7559\uff085.9 migration \u662f DDL-only \u7684\u4e8c\u6b21\u56de\u586b\uff0c\u4e0d\u6539\u5b57\u6bb5\uff09\uff0c\u6709\u6548\u53e3\u5f84\u4ee5 `_migrate_all()` \u5b9e\u9645\u8dd1\u5230\u7684\u6700\u540e\u4e00\u4e2a\u7248\u672c\u4e3a\u51c6 |",
    "\u2502 \u8bb0\u5fc6 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`\uff08v0.2+ \u542b cleanup \u5165\u53e3\uff0c\u89c1 ADR-0003\uff09<br>+ `snapshot/_tag_index.py`\uff08v0.5.x \u5171\u4eab\u539f\u8bed\uff0c\u89c1 ADR-0016\uff09+ `snapshot/count_cleanup.py`\uff08v0.11 \u6570\u91cf\u5151\u5e95\uff0c\u89c1 ADR-0016\uff09<br>+ `snapshot/age_cleanup.py`\uff08v0.11+ \u65f6\u95f4\u6e05\u7406 standalone \u955c\u50cf\uff0c\u4e0e `count_cleanup.py` \u5bf9\u79f0\uff0c\u89c1 ADR-0019\uff09<br>+ `snapshot/inspect.py`\uff08round 421 tag \u68c0\u89c6\u5de5\u5177\uff0c\u4e0e `_tag_index` \u5171\u4eab\u539f\u8bed\uff0c\u89c1 ADR-0025\uff09<br>`memory/manager.py` \u5f53\u524d\u6709\u6548 schema **5.11**\uff085.0 \u57fa\u7ebf + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`\uff08v0.5 5.9 \u4e8c\u6b21\u56de\u586b\uff09+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` \u91cd\u5efa + 5.4 `idx_facts_tags` \u91cd\u5efa + **5.10 `expires_ts` + TTL \u7d22\u5f15 + `recall_unexpired` / `purge_expired` / `set_ttl`** + **5.11 `access_count` + `idx_facts_access_count_ts` + `recall_most_accessed` / `recall_least_accessed` / `increment_access_count` LFU**\uff09\uff0c\u57fa\u7ebf\u89c1 ADR-0004\uff0c5.8 LRU \u589e\u91cf\u89c1 ADR-0008\uff0c5.9 \u7d22\u5f15\u56de\u586b\u89c1 ADR-0014\uff0c5.10 TTL + 5.11 LFU \u89c1 ADR-0025<br>\u6ce8\uff1a`SCHEMA_VERSION = 511`\uff085.11 \u5df2 bump\uff1b\u4e0e ADR-0014 \u5f53\u65f6\u8bb0\u5f55\u7684\u300c`SCHEMA_VERSION = 58` \u672a bump \u662f\u5df2\u77e5\u9057\u7559\u300d\u5df2\u4e0d\u4e00\u81f4 \u2014\u2014 5.9 \u2192 5.11 \u671f\u95f4 DDL \u591a\u6b21\u56de\u586b + `access_count` \u5b57\u6bb5\u65b0\u589e\u662f\u89e6\u53d1 bump \u7684\u771f\u56e0\uff0c\u89c1 ADR-0025 A1\uff09 |",
)

# D2 util
patch(
    "D2 util 8 \u2192 9 + print_guard",
    "  \u5f53\u524d **8 \u4e2a\u6a21\u5757**\uff1a`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n  `heartbeat` / `http_parents` / `web_search_rl`\uff08\u89c1 ADR-0001 D1\uff1bv0.1.1 +diary_archive/git_helpers\uff1bv0.2.7 +heartbeat\uff0c\u89c1 ADR-0008\uff1b\n  v0.2.8 +http_parents\uff0c\u89c1 ADR-0009\uff1bv0.13.2 +web_search_rl\uff0c\u89c1 ADR-0024\uff09\u3002",
    "  \u5f53\u524d **9 \u4e2a\u6a21\u5757**\uff1a`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n  `heartbeat` / `http_parents` / `web_search_rl` / `print_guard`\uff08\u89c1 ADR-0001 D1\uff1bv0.1.1 +diary_archive/git_helpers\uff1b\n  v0.2.7 +heartbeat\uff0c\u89c1 ADR-0008\uff1bv0.2.8 +http_parents\uff0c\u89c1 ADR-0009\uff1bv0.10 +print_guard\uff0c\u89c1 ADR-0018\uff1b\n  v0.13.2 +web_search_rl\uff0c\u89c1 ADR-0024\uff09\u3002",
)

# D3 scoring block
patch(
    "D3 \u00a72 scoring \u5360\u4f4d \u2192 v0.4 baseline",
    "\u251c\u2500\u2500 scoring/                   # \u5360\u4f4d\u5305\uff08v0.13.1 \u72b6\u6001\uff1a\u6301\u7eed\u4ec5 __pycache__/\uff0c\u7f3a __init__.py\uff0c\u672a git tracked\uff1b\n\u2502                             #   v0.3.1\uff08ADR-0012 / ADR-0013 D6\uff09\u767b\u8bb0\u9884\u7559 v0.4 \u8bc4\u5206\u57fa\u7ebf\uff1b\n\u2502                             #   v0.13.1\uff08ADR-0017\uff09\u91cd\u65b0\u786e\u8ba4\u4ecd\u672a\u5efa\u4e0d\u5220\uff1bROADMAP \u672a\u628a scoring/\n\u2502                             #   \u63d0\u4e3a blocked\uff0ccleanup \u51b3\u7b56\u7559\u7ed9\u540e\u7eed\u8f6e\u6b21\uff09",
    "\u251c\u2500\u2500 scoring/                   # v0.4 baseline \u5df2 ship\uff1a\u542f\u53d1\u5f0f score_turn (round 425) + 3 \u5e38\u91cf SCORE_ERROR / SCORE_OK_BASE / SCORE_RANGE\n\u2502                             #   __init__.py re-export + score.py \u5b9e\u73b0\uff08git tracked\uff1bcommit `8125486d` + `a1d51ee2`\uff09\n\u2502                             #   ROADMAP.md v0.4 \u8282\u4ecd\u5199\u300c\u8ba1\u5212\u300d\u5c5e ROADMAP drift\uff0c\u7559\u5f85 ROADMAP \u5355\u72ec round\uff08ADR-0025 D3\uff09",
)

# D4 snapshot/inspect
patch(
    "D4 \u00a72 snapshot + inspect.py",
    "\u251c\u2500\u2500 snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)\n\u2502                             #          \u65f6\u95f4\u6e05\u7406 standalone \u955c\u50cf\uff08\u4e0e count_cleanup \u5bf9\u79f0\uff09\uff0c\u8d70 _tag_index helper\n\u2502                             #          commit `fbe16191`\uff0c\u89c1 ADR-0019\uff1bside_git.py \u65e7 inline wrapper \u4fdd\u7559",
    "\u251c\u2500\u2500 snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)\n\u2502                             #          \u65f6\u95f4\u6e05\u7406 standalone \u955c\u50cf\uff08\u4e0e count_cleanup \u5bf9\u79f0\uff09\uff0c\u8d70 _tag_index helper\n\u2502                             #          commit `fbe16191`\uff0c\u89c1 ADR-0019\uff1bside_git.py \u65e7 inline wrapper \u4fdd\u7559\n\u251c\u2500\u2500 snapshot/inspect.py        # round 421: snapshot tag \u68c0\u89c6\u5de5\u5177\uff08\u4e0e `_tag_index` \u5171\u4eab\u539f\u8bed\uff09\uff0c\u89c1 ADR-0025",
)

# C2 memory/manager.py.bak.5.10
patch(
    "C2 \u00a72 memory + manager.py.bak.5.10",
    "\u251c\u2500\u2500 memory/manager.py          # MemoryManager\uff1aSQLite \u957f\u671f\u4e8b\u5b9e + compress_if_needed \u5c01\u88c5\n\u2502                             # \u5f53\u524d\u6709\u6548 schema 5.9\uff08v0.2.7 +LRU 5.8\uff1bv0.5 5.9 \u4e8c\u6b21\u56de\u586b 5.4/5.6 \u4e22\u5931\u7684\n\u2502                             # idx_facts_tags / idx_facts_title + \u914d\u5957 recent() method\uff09\uff0c\u89c1 ADR-0004 / ADR-0008 / ADR-0014",
    "\u251c\u2500\u2500 memory/manager.py          # MemoryManager\uff1aSQLite \u957f\u671f\u4e8b\u5b9e + compress_if_needed \u5c01\u88c5\n\u2502                             # \u5f53\u524d\u6709\u6548 schema 5.11\uff08v0.2.7 +LRU 5.8\uff1bv0.5 5.9 \u4e8c\u6b21\u56de\u586b 5.