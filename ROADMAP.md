# XRAgent 路线图

> 状态：v0.1 出生完成 · v1.0 稳定双 Agent 为最终目标

## v0.1 — 出生（✅ 当前）

**目标**：跑通 ReAct 循环 + 五大核心 + 24h 自愈 + 金蝉脱壳 + HTTP 父母通道。

**交付**：
- [x] 9 工具 + 工具黑名单 + 路径围栏
- [x] ReAct 循环 + MockBackend / LangChainBackend
- [x] HITL Gate 三态决策 + stdin 通道
- [x] SideGit snapshot + tag
- [x] 长期记忆 SQLite
- [x] 金蝉脱壳（commit → push → py_compile → 世代谱）
- [x] Watchdog / Supervisor 24h 自愈
- [x] HTTP 父母通道（/health /message /last-answer）
- [x] 32 单测 + 5 e2e = 37 用例

## v0.2 — 多 provider 适配（计划）

- OpenAI / DeepSeek / GLM / MiniMax 各跑通一次
- 断网 fallback 到 mock
- `--list-providers` CLI

## v0.3 — 长期记忆强化（部分 ✅: memory_recall 4f30bbe6; memory_recall_range / memory_top_frequent / memory_recall_by_tag 已上线; 待办: 摘要压缩 hook）

- `memory_save` / `memory_recall` 工具上线 ✅ (4f30bbe6)
  - memory_recall: 关键词 LIKE 召回, k clip [1,1000]
  - memory_recall_range: 时间窗口召回
  - memory_top_frequent: 频次 top-N
- `memory_recall_by_tag` 工具上线 ✅
  - tag 跨 category 横向召回, 走 idx_facts_tags
  - k clip [1,1000] + tag 空字符串早返
  - facts 字段在 4 字段契约上后置 tags (本工具特有)
- 事实按 category 索引 ✅ (idx_facts_category_ts 5.0)
- 摘要压缩 hook 启用（Agent 可写自己的压缩策略） — 待办

## v0.4 — 评分基线（计划）

- 每个 turn 加 `score` 字段（默认 None；测试通过率作为基线）
- N 轮无 score 提升 → 自动进入"长眠"

## v0.5 — 金蝉脱壳强化（部分）

- [x] commit → push → py_compile → supervisor 切换（v0.1 基础）
- [ ] 自动 rollback（如果新壳编译失败）
- [ ] 世代谱可视化（CLI `xragent generations`）

## v0.6 — 双分支雏形（计划）

- Agent A / Agent B 用 git worktree 隔离
- 单测级别对抗（不跑完整 ReAct 循环）
- 测试评分员（pytest + ruff + mypy 作为外部裁判）

## v0.7 — 自动评分员（计划）

- 蜕皮后自动跑 pytest / ruff / mypy
- score 写入世代谱
- 失败自动回滚到上一代

## v0.8 — HIL 升级（计划）

- 持续 stdin 流（实时中断）
- `interrupt` 命令强制停当前 turn
- HTTP /interrupt endpoint

## v0.9 — LangChain 评估（计划）

- 替换为 `openai` 原生 SDK + 自写 Tool 抽象
- 节省 30%+ 启动时间与依赖体积

## v1.0 — 稳定双 Agent（最终）

- A/B 分支 + 角色互换（每 10 轮）
- 记忆连续（同一份 facts.db + diary）
- 自动冻结开关（performance plateau 触发）
- 生产级框架固化

---

**更新规则**：
- 每达成一个版本，更新本文件 + diary 当天总结
- 路线图变更需写明原因（避免 silently 漂移）
- 不写"未来要做"的伪交付能力