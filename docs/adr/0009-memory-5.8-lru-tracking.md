# ADR-0009: memory 5.8 LRU 追踪（last_accessed_ts + touch_fact + recall_lru）

- 状态：已应用
- 触发 commit：1b0f123c（v0.2.7 / round 157）
- 关联文件：`src/xragent/memory/manager.py`

## 上下文

v0.2.6 及之前的 `MemoryManager` 只记 `created_ts`（插入时间），长期记忆没有
"最近被访问过"的信号。这意味着：

1. **冷数据回收没有依据**：长跑后 `facts` 表会持续膨胀，目前没有 LRU 维度
   让调用方挑出最久未访问的 top-k 来淘汰。
2. **召回统计缺维度**：现有 4 种 recall（关键词 / 时间窗 / 频次 / 标签，
   见 ADR-0004 / ADR-0007）都不区分"刚召回过"与"从没人碰过"的事实，
   调试时无法回答"哪些 fact 长期喂给 LLM 但没人复核"。

## 决策

在 `memory/manager.py` 加 `Fact.last_accessed_ts` 字段 + `idx_facts_last_accessed_ts`
索引 + `touch_fact` / `recall_lru` 方法：

- `Fact.last_accessed_ts: float = 0.0`（`REAL NOT NULL DEFAULT 0.0`）。
  - `save_fact` 插入新行时初始化为 `ts`（创建即"访问"），避免新行被
    `recall_lru` 误判为冷数据。
  - 迁移路径：`last_accessed_ts` 列若不存在则 `ALTER TABLE` 添加，老行保持
    `0.0`，既表示"从未被 touch 过"，也保证 `recall_lru` 把老行排在最前
    （适合冷数据淘汰 / 内存压力时的低优先级回收）。
- `touch_fact(fact_id)`：把指定 fact 的 `last_accessed_ts` 刷新为当前时间。
  调用方在每次把 fact 喂给 LLM / 召回时都应该 touch 一下，让 `recall_lru`
  能反映"刚被用过"。
- `recall_lru(k=10)`：按 `last_accessed_ts ASC` 取 top-k（最久未访问在前），
  二级排序 `ts ASC` 保证老行间稳定。
- 索引：`idx_facts_last_accessed_ts(last_accessed_ts ASC)`，让 ORDER BY
  `last_accessed_ts ASC LIMIT k` 走索引而不是全表扫描。

## 为什么不用 "last_recall_ts" 之类更准确的命名

`last_accessed_ts` 与 `accessed_at` 是事实层的"最近被任何方式访问过"语义；
未来若加 `recall_ts` / `inject_ts` 细分维度，只需在 Fact 上加新字段而不是
改名（迁移更便宜）。命名上保留 `last_*` 前缀表示"最近一次"。

## 边界

- `0.0` 哨兵值承担"从未访问过"的语义，不另设 `is_visited` 布尔列——
  节省一列宽度，且排序时 `0.0` 自然沉底，正好是冷数据回收想要的顺序。
- 不引入自动淘汰策略：5.8 只提供"挑出最久未访问"的工具，淘汰由调用方
  决策。后续若要做内存上限自动 trim，应在 `MemoryManager` 上另起方法，
  不在 `recall_lru` 里副作用删除。

## 影响

- `architecture-v0.md` §一 / §二 memory 路径补"`last_accessed_ts` /
  `touch_fact` / `recall_lru`（v0.2.7 LRU 追踪，见 ADR-0009）"；§五版本
  对照加 v0.2.7 行（与 ADR-0008 共享一行）。
- `Fact` 模型字段 +1；迁移脚本自动升级老 DB，不需要人工干预。
- 4 种 recall 工具（`memory_recall` / `memory_recall_range` /
  `memory_top_frequent` / `memory_recall_by_tag`）目前不调用 `touch_fact`——
  是否要在每次 recall 命中时 touch 一行，留待后续 round 决定；现在
  `recall_lru` 是显式入口，调用方主动调。