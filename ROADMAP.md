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

## v0.5 — 金蝉脱壳强化（部分 → 推进 v0.5.x）

- [x] commit → push → py_compile → supervisor 切换（v0.1 基础）
- [x] 5.9 schema 整理: 恢复 5.4/5.6 丢失的 idx_facts_tags + idx_facts_title 索引 + 配套 method (recall_by_tag/recall_by_title/update_title/recent)
- [x] LLM-facing wrappers 完整性: memory_recall_by_tag / memory_recall_by_title / memory_update_title 全部上线
- [x] memory_tools registry 注册完整性
- [x] evolve_tools.py 5.x 重构碎片整理: 与 test_evolve_tools.py 契约对齐 (RUNTIME_STATE_KEY_* 常量 + dry_run/suppress_restart)
- [ ] 自动 rollback（如果新壳编译失败）— plan
- [ ] 世代谱可视化（CLI `xragent generations`）— plan

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

## v0.10 — Interactive TUI Channel（CT0 强制）

> **来源**: CM (父母) 2026-08-02 22:00 显式指令 (`scripts/chat` 已实装).
> **目标**: 让父母可以通过 terminal 直接和 Agent 对话, 不必靠 launchd
> / HTTP 写代码. TUI 应能在 agent autonomous 时实时打断 + 注入任务.

- [x] scripts/chat (HTTP 父母通道终端化) — banner / spinner / /tools / /memory / /gens / /meta / /status / /help
- [x] ANSI 色彩 (NO_COLOR 关掉 / pipe 退化)
- [x] readline 历史 (~/.xragent_chat_history)
- [x] HTTP /tools / /memory/recent / /generations / /metamorphose 端点
- [ ] 流式输出 (SSE / chunked) — plan: 计划用 /message + last-answer streaming chunk
- [ ] 中断当前 round — plan: HTTP /interrupt endpoint + autonomous 主循环尊重 interrupt_event
- [ ] 会话历史持久化 — plan: memory.jsonl 追加, 让 agent 跨 session 看对话历史
- [ ] 自动补全 (readline completer) — plan: 复用 AGENTS.md 自省 + 当前 task template

## v0.11 — 底层逻辑优化 + 自我热更新（CT0 强制）

> **来源**: CM (父母) 2026-08-02 22:00 显式指令.
> **目标**: 把核心逻辑 (ReActLoop / HitlGate / MemoryManager / SideGit) 优化
> 到可维护 / 可热更, 让金蝉脱壳能在 running autonomous 时无缝切换.

- [x] 测试基础设施恢复: 866 tests pass (从 baseline 0 起步, 修了 5.7 重构 -456 行
      丢失的索引/method/wrapper + 5.x 5 个 import 漏)
- [x] deadlock 触发器 patch (autonomous.py 的 "无 src/ 改动 → revert HEAD" 触发器
      显式 F-1/F-2/F-3 + G-1/G-2/G-3 分支; 历史 31 轮死循环实证不可靠)
- [x] **SideGit snapshot cleanup 加 dry_run 输出** ✅ (round 206+ a59beb18)
      - cleanup_old_snapshots + count_cleanup 两条路径都走 _tag_index helper
      - 行格式 %09 / \t 改一处时不再漂移（消除 3 处重复）
      - time-cleanup 与 count-cleanup 共享 list/delete helper
- [ ] 优化候选 (优先级建议, 父母可调):
      - ReActLoop: 拆分 token 计量 / step 边界判断 → 单元测试粒度
      - HitlGate: 加 `risk=medium` 工具的"累计 N 次自动放行"窗口
      - MemoryManager: top_frequent / recall_lru 走 idx, 加 CLI: `xragent memory stats`
- [ ] 金蝉脱壳增强:
      - metamorphose 加 pre-flight: 编译失败自动回滚 (recover HEAD)
      - generation.jsonl 加 score 字段 (pytest 通过率 / lint 0 警告)
      - 世代谱可视化: `xragent generations [--since N] [--tree]`

## v0.5.x — 触发器盲区 (CT0 强制)

- [x] autonomous.py 触发器改 F-1/F-2/F-3 + G-1/G-2/G-3 四档显式分流 (取代 31 轮死循环)
- [x] **snapshot helper 收归 _tag_index** ✅ (round 206+ a59beb18)
      - _list_xragent_turn_tags_with_dates / _delete_xragent_turn_tag 重复 inline 收归
      - count_cleanup.py / cleanup_old_snapshots 两条路径共享 list + delete helper
- [ ] agent 自己再加一道 determinstic guard: autonomous driver 在跑任务前显式
      检查 HEAD 类型, 不依赖 LLM 文本记忆. 给未来 LLM swap (5.x → 6.x) 留 robustness.

---

**更新规则**：