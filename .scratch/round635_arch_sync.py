"""round 635 - architecture-v0.md 9 处 str.replace 落地 ADR-0026"""
import sys

with open('docs/architecture-v0.md', 'r', encoding='utf-8') as f:
    txt = f.read()

original = txt

# === D7: 顶部 ADR 索引 ===
old_d7 = (
    '> [ADR-0024](adr/0024-architecture-v0-round-582-actual-doc-landing.md)'
    '（v0.13.2 round 582 doc sync：autonomous journal（diary 头部预览 + round_done 留痕）'
    '+ autonomous rng 显式参数化（可选）+ tools/web_search.py 5min 限流改造（per-host throttle）；'
    '§一 / §三 / §四 / §五 全部 doc 同步落地）。'
)
new_d7 = old_d7 + (
    '\n> [ADR-0025](adr/0025-architecture-v0-round-588-drift-scan-design.md)'
    '（round 588 drift 扫描设计：列出 10 项 code-vs-doc 失真 A1-A3/B1-B2/C1-C2 + 7 项修复方案 D1-D7'
    ' —— 仅 doc 同步设计，未落地）。'
    '\n> [ADR-0026](adr/0026-architecture-v0-round-635-adr-0025-actual-landing.md)'
    '（round 635 close-out：实际落地 ADR-0025 D1-D7 + D2\u0027 print_guard 二次入表'
    ' —— 仅 doc 同步，未碰 src/）。'
)
assert txt.count(old_d7) == 1, 'D7'
txt = txt.replace(old_d7, new_d7)
print('D7 done')

# === A1_1 ===
old_a1_1 = (
    '`memory/manager.py` 当前有效 schema **5.9**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + '
    '5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + '
    '5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建），'
    '基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见 ADR-0014'
)
new_a1_1 = (
    '`memory/manager.py` 当前有效 schema **5.11**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + '
    '5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + '
    '5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建 + '
    '5.10 `expires_ts` TTL（commit `cb13c186`，见 ADR-0025 A1）+ '
    '5.11 `access_count` LFU（commit `cb13c186`，见 ADR-0025 A1）），'
    '基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见 ADR-0014，'
    '5.10/5.11 schema 实际落地见 ADR-0025 + ADR-0026'
)
assert txt.count(old_a1_1) == 1, 'A1_1'
txt = txt.replace(old_a1_1, new_a1_1)
print('A1_1 done')

# === A1_3 ===
old_a1_3 = (
    '注：常量 `SCHEMA_VERSION = 58` 未 bump 是已知遗留（5.9 migration 是 DDL-only 的二次回填，'
    '不改字段），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准'
)
new_a1_3 = (
    '常量 `SCHEMA_VERSION = 511  # 5.11`（commit `cb13c186` 已 bump，'
    '与 `_migrate_v510()` / `_migrate_v511()` 同步；5.10/5.11 增量字段 `expires_ts` / `access_count` '
    '与 schema 版本号一致），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准'
)
assert txt.count(old_a1_3) == 1, 'A1_3'
txt = txt.replace(old_a1_3, new_a1_3)
print('A1_3 done')

# === A1_2 + A2_2 ===
old_a1_2 = (
    '│                             # 当前有效 schema 5.9（v0.2.7 +LRU 5.8；v0.5 5.9 二次回填 5.4/5.6 丢失的\n'
    '│                             # idx_facts_tags / idx_facts_title + 配套 recent() method），'
    '见 ADR-0004 / ADR-0008 / ADR-0014'
)
new_a1_2 = (
    '│                             # 当前有效 schema 5.11（v0.2.7 +LRU 5.8；v0.5 5.9 二次回填 5.4/5.6 丢失的\n'
    '│                             # idx_facts_tags / idx_facts_title + 配套 recent() method；v0.5.x +TTL 5.10\n'
    '│                             # +LFU 5.11 增量：expires_ts / access_count + recall_unexpired / set_ttl /\n'
    '│                             # touch_fact + recall_most_accessed，'
    '见 ADR-0004 / ADR-0008 / ADR-0014 / ADR-0025 / ADR-0026'
)
assert txt.count(old_a1_2) == 1, 'A1_2'
txt = txt.replace(old_a1_2, new_a1_2)
print('A1_2 done (A2_2 same line)')

# === A2_1: scoring/ 占位段 ===
old_a2_1 = (
    '├── scoring/                   # 占位包（v0.13.1 状态：持续仅 __pycache__/，缺 __init__.py，未 git tracked；\n'
    '│                             #   v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 v0.4 评分基线；\n'
    '│                             #   v0.13.1（ADR-0017）重新确认仍未建不删；ROADMAP 未把 scoring/\n'
    '│                             #   提为 blocked，cleanup 决策留给后续轮次）'
)
new_a2_1 = (
    '├── scoring/                   # v0.4 baseline 已 ship（git tracked，commit `8125486d` + `a1d51ee2`）：\n'
    '│                             #   __init__.py + score.py；导出 score_turn + 3 常量（SCORE_ERROR / SCORE_OK_BASE /\n'
    '│                             #   SCORE_RANGE）；v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 → v0.4 实际落地 →\n'
    '│                             #   round 562 ADR-0023 二次确认，round 635 ADR-0026 doc 同步'
)
assert txt.count(old_a2_1) == 1, 'A2_1'
txt = txt.replace(old_a2_1, new_a2_1)
print('A2_1 done')

# === B1: snapshot/inspect.py ===
old_b1 = (
    '├── snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)\n'
    '│                             #          时间清理 standalone 镜像（与 count_cleanup 对称），走 _tag_index helper\n'
    '│                             #          commit `fbe16191`，见 ADR-0019；side_git.py 旧 inline wrapper 保留'
)
new_b1 = old_b1 + (
    '\n├── snapshot/inspect.py        # v0.5.x round 421 (commit `467bf563`)：snapshot 只读 + 展示层\n'
    '│                             #          4 公开 API：SnapshotMeta + list_snapshots_with_meta +\n'
    '│                             #          count_over_age + format_snapshot_table；不引入 git 写操作，\n'
    '│                             #          与 count_cleanup.py / age_cleanup.py（写入层）对称；见 ADR-0026 B1'
)
assert txt.count(old_b1) == 1, 'B1'
txt = txt.replace(old_b1, new_b1)
print('B1 done')

# === D2': §一补充说明 util/ 8 -> 9 ===
old_d2_sup = (
    '  当前 **8 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n'
    '  `heartbeat` / `http_parents` / `web_search_rl`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；\n'
    '  v0.2.8 +http_parents，见 ADR-0009；v0.13.2 +web_search_rl，见 ADR-0024）。'
)
new_d2_sup = (
    '  当前 **9 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /\n'
    '  `heartbeat` / `http_parents` / `web_search_rl` / `print_guard`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；\n'
    '  v0.2.8 +http_parents，见 ADR-0009；v0.10 +print_guard，见 ADR-0018；v0.13.2 +web_search_rl，见 ADR-0024；v0.10 二次入表，见 ADR-0026 D2\u0027）。'
)
assert txt.count(old_d2_sup) == 1, 'D2_sup'
txt = txt.replace(old_d2_sup, new_d2_sup)
print('D2_sup done')

# === D2': §二 util/ treelist 8 -> 9 ===
old_d2_tree = (
    '├── util/                      # 8 个模块：json_utils / jsonl_utils / subprocess_utils\n'
    '│                             #          / diary_archive / git_helpers / heartbeat / http_parents\n'
    '│                             #          / web_search_rl（v0.13.2 见 ADR-0024）\n'
    '│                             #   heartbeat.py:   start_heartbeat_thread（v0.2.7，见 ADR-0008）\n'
    '│                             #   http_parents.py: setup_http_parents_channel（v0.2.8，见 ADR-0009）\n'
    '│                             #   web_search_rl.py: per-host 5min 限流（Throttle + ThrottleState + acquire_slot，v0.13.2，见 ADR-0024）'
)
new_d2_tree = (
    '├── util/                      # 9 个模块：json_utils / jsonl_utils / subprocess_utils\n'
    '│                             #          / diary_archive / git_helpers / heartbeat / http_parents\n'
    '│                             #          / web_search_rl / print_guard（v0.10 见 ADR-0018 + 二次入表见 ADR-0026 D2\u0027）\n'
    '│                             #   heartbeat.py:   start_heartbeat_thread（v0.2.7，见 ADR-0008）\n'
    '│                             #   http_parents.py: setup_http_parents_channel（v0.2.8，见 ADR-0009）\n'
    '│                             #   web_search_rl.py: per-host 5min 限流（Throttle + ThrottleState + acquire_slot，v0.13.2，见 ADR-0024）\n'
    '│                             #   print_guard.py:  print 二次入表兜底（v0.10，见 ADR-0018 / ADR-0026 D2\u0027）'
)
assert txt.count(old_d2_tree) == 1, 'D2_tree'
txt = txt.replace(old_d2_tree, new_d2_tree)
print('D2_tree done')

# === D3: §四 scoring/ 不变量行 ===
old_d3 = (
    '| scoring/ 目录占位 | `src/xragent/scoring/` v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，'
    '未 git tracked；v0.3.1 登记预留 v0.4 评分基线（ADR-0012 / ADR-0013 D6）；v0.13.1 重新确认仍未建不删，'
    'cleanup 决策留给后续轮次（见 ADR-0017） |'
)
new_d3 = (
    '| scoring/ v0.4 baseline 已 ship | `src/xragent/scoring/` 当前状态：v0.4 baseline 已 ship'
    '（git tracked，commit `8125486d` + `a1d51ee2`）；`__init__.py` + `score.py` 都已 git tracked；'
    '导出 `score_turn` + 3 常量（`SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE`）；'
    'v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 → v0.4 实际落地 → round 562 ADR-0023 二次确认 → '
    'round 635 ADR-0026 doc 同步；占位包措辞已在 v0.10 ADR-0018 / round 325 ADR-0021 / '
    'round 562 ADR-0022 三轮改正，本 ADR-0026 终态确认 |'
)
assert txt.count(old_d3) == 1, 'D3'
txt = txt.replace(old_d3, new_d3)
print('D3 done')

# === D5: §五版本对照表 — 在 v0.13.2 行前补 5 行 ===
old_d5 = '| v0.13.2 (round 582) |'

v04_line = (
    '| v0.4 | `scoring/` baseline 实际落地：`__init__.py` + `score.py` 都 git tracked，'
    '导出 `score_turn` + 3 常量（`SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE`）；'
    'commit `8125486d`（__init__.py）+ `a1d51ee2`（score.py）。'
    'round 562 ADR-0023 + round 635 ADR-0026 doc 同步 | ADR-0026 A2 |'
)
v0510_line = (
    '| v0.5.10 | `memory/manager.py` schema 5.10：`expires_ts`（INTEGER，可空）+ '
    '`recall_unexpired(limit=...)` + `set_ttl(fact_id, ttl_s)`；commit `cb13c186` 同期；'
    'TTL 仅追加字段、不删旧 fact、不改 `_migrate_all()` 顺序；`_migrate_v510()` 幂等执行'
    ' | ADR-0025 A1 / ADR-0026 A1 |'
)
v0511_line = (
    '| v0.5.11 | `memory/manager.py` schema 5.11：`access_count`（INTEGER default 0）+ '
    '`touch_fact(fact_id)` bump + `recall_most_accessed(limit=...)`；LFU 排序工具，'
    '复用 `recall_lru` 同一索引基础设施；commit `cb13c186` 同期；'
    '与 5.8 LRU 互补（LRU = 时间、LFU = 频次），`_migrate_v511()` 幂等执行；'
    '`SCHEMA_VERSION = 511` 一并 bump | ADR-0025 A1 / ADR-0026 A1 |'
)
v10_print_line = (
    '| v0.10 (print_guard 二次入表) | `util/print_guard.py` 二次入表'
    '（ADR-0018 round 215+ 已抽模块但 §一 §二 §五多处漏登记）；'
    'round 635 ADR-0026 D2\u0027 一并修：§一「当前 8 个模块」→「9 个模块」+ '
    '§二 util/ treelist 末尾补 print_guard.py + §五本行；'
    'commit 已在 ADR-0018 落地，doc 同步属本轮 ADR-0026 | ADR-0018 / ADR-0026 D2\u0027 |'
)
v05x_inspect_line = (
    '| v0.5.x (round 421) | `snapshot/inspect.py` 抽取：'
    '4 公开 API（SnapshotMeta + list_snapshots_with_meta + count