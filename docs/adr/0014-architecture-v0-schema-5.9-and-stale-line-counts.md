# ADR-0014: architecture-v0 schema 5.8 → 5.9 drift + §五 v0.5 schema consolidation 行缺失 + 行数 stale

- 状态：已接受
- 日期：2026-08-03
- 决策者：XRAgent（autonomous round 204+）

## 背景

`docs/architecture-v0.md` 自 ADR-0013（v0.3.1 doc landing, commit `8301415d`）以来又积累了 3 处与 `src/xragent/` 实际代码不一致：

1. **§一「记忆」行 schema 描述过时**：
   doc 写「当前 schema **5.8**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU）」。
   但 `src/xragent/memory/manager.py`：

   - `SCHEMA_VERSION = 58`（**未 bump**，但这不是有效口径——有效口径是 `_migrate_all()` 实际跑了哪些 migration）。
   - `_migrate_all()` 在第 281-289 行依次调用 `_migrate_v51 / v53 / v54 / v55 / v56 / v57 / v58 / v59`，最后一步 `_migrate_v59()` 是：

     > 5.8 -> 5.9: 恢复 5.4/5.6 时代丢失的 idx_facts_tags / idx_facts_title 两个索引。
     > 仅 DDL, 不动 data; 老库已存在则 CREATE INDEX IF NOT EXISTS 直接跳过。
     > 现状对账:
     >   * idx_facts_tags  (5.4) — 5.7 大重构 (-456 行) 时随 method recall_by_tag 一并遗失。
     >   * idx_facts_title (5.6) — 5.7 重构时随 method recall_by_title / update_title 一并遗失。

   - 所以**有效 schema 是 5.9**，doc 描述里的「当前 5.8」是 stale 的——读 doc 的人会以为 5.9 不存在，但代码每轮 init 都在跑 5.9 迁移。

   - 同时 schema 演进链描述跳过了 **5.4**（`idx_facts_tags`）——5.4 是 v0.2 早期加的索引，doc 完全没提，5.9 是它的二次回填。

2. **§五 版本对照表缺 v0.5 schema consolidation 行**：
   ROADMAP.md v0.5 明确记 `[x] 5.9 schema 整理: 恢复 5.4/5.6 丢失的 idx_facts_tags + idx_facts_title 索引 + 配套 method (recall_by_tag/recall_by_title/update_title/recent)` 为已完成。
   但 architecture-v0.md §五最后一行是 v0.3.1（ADR-0012 / 0013），整个 v0.5 没有任何 doc 落地痕迹。

3. **§二 `tools/registry.py` 行注释「305 行」stale**：
   `wc -l src/xragent/tools/registry.py` → 317 行（ADR-0011 落地时是 305，v0.3.1 又多了 ~12 行：memory_recall_by_title / memory_update_title 注册 + `build_default_registry` 注释展开）。

前两条是真实 drift（doc 误导读者以为 schema 是 5.8、以为 v0.5 没发生）；第三条是纯行数 stale（同样会误导读者以为 registry.py 没动）。

## 决策

### D1 — §一「记忆」行 schema 描述改为 5.9 + 补 5.4 / 5.9

把：

> `memory/manager.py` 当前 schema **5.8**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU），基线见 ADR-0004，5.8 LRU 增量见 ADR-0008

改为：

> `memory/manager.py` 当前有效 schema **5.9**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建），基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见本 ADR-0014
>
> 注：常量 `SCHEMA_VERSION = 58` 未 bump 是已知遗留（5.9 migration 是 DDL-only 的二次回填，不改字段），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准。

### D2 — §二 `tools/registry.py` 行注释行数 305 → 317

把：

> │                             # （v0.2.10 抽出 _safe_call helper，305 行，结构展开）：

改为：

> │                             # （v0.2.10 抽出 _safe_call helper + v0.3.1 +memory_recall_by_title / +memory_update_title 注册，317 行，结构展开）：

### D3 — §五 版本对照表补 v0.5 schema consolidation 行

在 v0.3.1 行后插入：

| v0.5 (✅ 部分) | memory schema 5.9 整理：`_migrate_v59()` 恢复 5.4/5.6 时代随 5.7 -456 行重构丢失的 `idx_facts_tags` / `idx_facts_title` 两个索引（DDL-only，幂等 CREATE INDEX IF NOT EXISTS）；配套补 `manager.recent()` method（不过滤 archived，用于调试 / 复盘）；evolve_tools.py 与 test_evolve_tools.py 契约对齐（`RUNTIME_STATE_KEY_*` 常量 + `dry_run` / `suppress_restart` 参数）。doc 同步：本 ADR-0014（§一 schema 5.8 → 5.9 + §二行数 305 → 317 + §五本行）。未做：`SCHEMA_VERSION` 常量 bump（已知遗留，5.9 是 DDL-only 二次回填不增字段）、自动 rollback / 世代谱可视化 | ADR-0014 |

### D4 — 顶部 ADR 链接表补 ADR-0014

在 ADR-0013 行后追加：

> [ADR-0014](adr/0014-architecture-v0-schema-5.9-and-stale-line-counts.md)（v0.5：schema 5.9 整理 doc sync + §一 5.8→5.9 + §二 registry.py 行数 305→317 + §五 v0.5 行落地）。

## 影响

- §一「记忆」行的读者以后能拿到 5.9 这个正确口径；schema 演进链不再跳 5.4。
- §五版本对照表首次反映 v0.5（之前完全空白，与 ROADMAP v0.5 已完成项不一致）。
- §二`tools/registry.py` 行注释与 `wc -l` 一致。

## 不做

- 不 bump `SCHEMA_VERSION = 58` 常量。理由：5.9 migration 是 DDL-only 的索引二次回填，没新增字段/列；常量口径是「最大字段版本」，保持 58 不变；如果未来真有新字段，会显式 bump 并写 `_migrate_v510()`，与现在这条 5.9 的语义无关。在 doc 里把这一点明说（见 D1 的注），避免下次又有人按字面 bump 制造 schema migration 噪音。
- 不动 §二 `memory/manager.py` 行注释里的 schema 版本字符串（已经是 `当前 schema 5.8`，会被 D1 一起改）。
- 不在 §五加 v0.10 / v0.11 行：scripts/chat (TUI) 和 v0.11 优化属于 ROADMAP 层面的进展，不属于 architecture-v0.md 关注的 `src/xragent/` 模块结构；混入会让 §五 表头「关键事件」与 ROADMAP 重叠，分工不清。