# ADR-0004: 工具清单 14 → 15 + `memory_recall` 工具入表

> 状态：已采纳。
> 时间：v0.2.3 之后，autonomous turn 自检 `docs/architecture-v0.md` ↔ `src/xragent/` 实际代码时发现。
> 上游 ADR：ADR-0002（上次架构同步）/ ADR-0003（snapshot 保留）。

## 一、背景

`docs/architecture-v0.md` §三 注册工具表长期声称 **14 个** 工具，但
`src/xragent/tools/registry.py::build_default_registry()` 实际注册了 **15 个**
工具。少的那一个就是 `memory_recall`（关键词 LIKE 召回，对应
`src/xragent/tools/memory_tools.py::memory_recall`）。

它和另外两个 recall 工具构成完整的"3 种 recall 风格"三角：

| 工具 | 回答的问题 | 实现 |
| --- | --- | --- |
| `memory_recall`        | "我说过什么关于 X 的事"（关键词 LIKE） | `fact.content LIKE '%q%' ORDER BY ts DESC` |
| `memory_recall_range`  | "什么时候说的"（时间窗口）            | `ts BETWEEN ? AND ?`        |
| `memory_top_frequent`  | "反复说过的点是什么"（频次 top-N）    | `GROUP BY content HAVING count >= ?` |

`src/xragent/tools/memory_tools.py` 模块 docstring 里也明确写
"3 个 recall 风格工具 (`memory_recall` / `memory_recall_range` / `memory_top_frequent`)"，
并通过 `_K_LIMIT_MIN` / `_K_LIMIT_MAX` / `_clip_limit` 三个工具共享 k 兜底逻辑，
确认这三者是平级设计、不该缺一。

## 二、文档漂移点

1. §二 模块清单末尾："工具总数：**14 个**" → 实际 15
2. §二 模块清单末尾："`evolution_enabled=false` 时剩 12 个" → 实际剩 13（15 − 2）
3. §三 注册工具表：缺 `memory_recall` 整行
   - 风险等级：**low**（同其他 recall 工具，只读长期记忆）
   - HITL：不需要
   - 输入 schema：`{query: string=default="", k: int=default=5, category?: string}`

## 三、决策

1. `docs/architecture-v0.md` §二 工具总数 14 → **15**；"剩 12 个" → "剩 13 个"。
2. §三 注册工具表按"save → recall → recall_range → top_frequent"顺序补 `memory_recall` 行。
3. §四 关键不变量表保持不变（HITL 门仍只覆盖 high-risk；`memory_recall` 走 low-risk 直通）。
4. `build_default_registry()` 代码不动 —— 这是**纯文档同步**，不是新增功能。

## 四、影响

- LLM-facing 工具契约 **+1**；当前 system prompt（`core/dream.py::assemble_system_prompt`）
  没显式提示 memory_recall，所以 Agent 这轮仍可能"知道存在但没想起来用"。
- 是否要在 system prompt 里加"补上下文时优先 `memory_recall`"的提示，留给
  v0.3"长期记忆强化"范畴单独决策（已在 ROADMAP v0.3 留位）。
- 测试 / snapshot 清理 / HITL / autonomous 节奏：**零影响**。

## 五、取舍

- **为什么加 ADR 而非直接改文档**：沿用 ADR-0002 / ADR-0003 的二件套模式
  （"每次架构同步都留痕"），便于后续 git log 一眼回溯漂移事件。
- **为什么不顺手把 `memory_recall` 提到 system prompt**：v0.2.x 阶段"补上下文"
  还不是高频路径，过早注入会让 Agent 在不该 LIKE 搜索的场景里滥用。
  v0.3 的 recall 强化阶段会一次性把三个 recall 工具都接进 prompt。
- **不调整 util/ 模块数（仍 5）**：ADR-0001 已锁定，diary_archive / git_helpers
  是 v0.1.1 后续增量，未再变动。