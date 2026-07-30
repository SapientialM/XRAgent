# ADR-0008: architecture-v0.md 同步 util/heartbeat.py + memory schema 5.8 LRU（v0.2.7 重做）

> 状态：已采纳（v0.2.7）
> 时间：2026-07-31（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
> 上游 ADR：ADR-0006（v0.2.5 重做）/ ADR-0007（v0.3 工具面 + read_file.original_size）
> 前置 history：commit `b78638d1 docs(architecture): sync v0.2.7 — util/heartbeat.py + memory 5.8 LRU`（被 `348d6f33` revert）
>              commit `381c5b8b chore(generations): round 158 close-out (util/heartbeat.py ...)`（被 `ed2bcb3b` revert）
>              commit `1a3d1d42 util/heartbeat.py: extract duplicated heartbeat thread pattern`（**保留**，是 util/ 新模块的真正落地）

## 一、背景

v0.2.7 在 src/ 侧实际落地了两件事，但 `docs/architecture-v0.md` 没跟上：

1. **util/ 新增 `heartbeat.py`**（commit `1a3d1d42`）：把 `main.py` 里 `cmd_interactive` / `cmd_autonomous`
   两处重复的 7 行 `while not <stop>: try: rs.heartbeat(); except: pass; wait(<interval>)`
   模板抽到 `util/heartbeat.py::start_heartbeat_thread(stop_predicate, interval_s, name)`，
   两处调用点各塌成一行。属于"出现 2+ 次且 ≥5 行"原则触发，符合 `util/__init__.py` docstring 的抽取口径。

2. **memory schema 5.8 LRU**（commit `1b0f123c feat(memory): 5.8 LRU 追踪 — last_accessed_ts + touch_fact + recall_lru`）：
   `Fact.last_accessed_ts` / `idx_facts_last_accessed_ts` / `MemoryManager.touch_fact` /
   `MemoryManager.recall_lru`。接 ADR-0007 §2.5 留的口 — 本轮按 ADR-0007 的规划由本 ADR 收纳。

但前一轮 round 158 试图把 v0.2.7 写进 doc（commit `b78638d1` + `381c5b8b`）时**两次被 revert**（`348d6f33` + `ed2bcb3b`），
doc 回到 v0.2.6 状态，两处失实全部复发。本轮重新触发 `TASK_TEMPLATES[6]` 时再次撞回同一组漂移，
证明 v0.2.7 的盘点方向正确、只是落地被回滚，本次按 ADR-0007 同款决策意图重做。

## 二、为什么不直接 cherry-pick b78638d1 / 381c5b8b

不能直接 cherry-pick，原因：

1. **不是单纯 cherry-pick 能修的**：本轮的 src/ 状态（commit `1a3d1d42` 已落地 + commit `22469503` 已合并 + commit `9ad02b6f` 已合并）
   跟 `b78638d1` 当时的状态一致，所以 cherry-pick 实质上**不会冲突**。但 ADR-0006 已经立过 precedent：
   文档同步的 ADR **应单独留痕**，把"落地 → revert → 重做"三件事在 git log 里一眼可看，而不是把决策意图埋进别人的 commit message。
2. **ADR-0007 §2.5 留的口由本 ADR 收纳**：5.8 LRU 是 ADR-0007 文档明确推迟到 ADR-0008 的内容，
   单独 ADR 比"塞回 ADR-0007"更符合 ADR-0007 §四 "memory schema 5.x 全量说明留给 ADR-0008" 的明文要求。
3. **patch 本身可重写得更准确**：`b78638d1` 把 util/ 写成"6 个模块"，但 `util/__init__.py` 本身**没有 re-export**
   `start_heartbeat_thread`（`from __future__ import annotations` 之后就空文件），5 个原模块同样如此；
   本轮 patch 在 doc 上明确写"start_heartbeat_thread 是 util/ 的 6 号公开 API，但 `util/__init__.py` 选择不 re-export，
   调用方用 `from xragent.util.heartbeat import start_heartbeat_thread`（与 main.py 当前用法一致）"，
   比 `b78638d1` 更贴合代码现状。

## 三、漂移点（code 为准）

| # | 漂移点 | 文档旧值 | 实际 |
|---|--------|---------|------|
| 1 | §一 util/ 注释 | "当前 5 个模块" + 清单 `json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers` | **6 个**：再加 `heartbeat.py` (`start_heartbeat_thread`) |
| 2 | §二 util/ 注释 | "5 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers" | **6 个**：再加 `heartbeat.py` |
| 3 | §五 版本对照 | 缺 v0.2.7 | 需要补：util/heartbeat.py 抽取 + memory schema 5.8 LRU（ADR-0008） |
| 4 | memory schema 版本说明 | ADR-0007 §2.5 已点名"memory schema 5.x 全量说明留给 ADR-0008"，§一正文 / §二正文 仍只提 ADR-0004 (5.0) | 应在 ADR-0008 收纳 5.8 LRU，并在 §一正文 / §二正文提"schema 已迭代至 5.8，见 ADR-0004 / ADR-0008" |

## 四、决策

### D1. §一 util/ 注释升级 5 → 6

把 §一 util/ 注释从

```
当前 5 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers`
（见 ADR-0001 D1，diary_archive + git_helpers 为 v0.1.1 后续增量）。
```

改成

```
当前 6 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` / `heartbeat`
（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008）。
`heartbeat.py::start_heartbeat_thread(stop_predicate, interval_s, name)` 把 main.py 中
两处重复的 7 行 `while not <stop>: try: rs.heartbeat(); except: pass; wait(<interval>)`
模板收敛到一处；`util/__init__.py` 不 re-export，调用方按 `from xragent.util.heartbeat import ...` 直接用
（main.py 当前用法）。
```

### D2. §二 util/ 行加 `heartbeat.py`

§二 模块清单的 util/ 行从

```
├── util/                      # 5 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers
```

改成

```
├── util/                      # 6 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers / heartbeat
│                             #   heartbeat.py: start_heartbeat_thread（v0.2.7，见 ADR-0008）
```

### D3. §五 版本对照补 v0.2.7 行

紧跟 v0.2.6 行后插入 v0.2.7：

```
| v0.2.7 | 架构 doc 同步：util/heartbeat.py 抽取（5 → 6 模块）+ memory schema 5.8 LRU（last_accessed_ts / touch_fact / recall_lru）。
           util/heartbeat.py 落地 commit 1a3d1d42；doc 同步 commit b78638d1 被 348d6f33 revert，
           round 158 close-out commit 381c5b8b 被 ed2bcb3b revert；本 ADR-0008 重做 | ADR-0008 |
```

### D4. §一正文 / §二正文 memory schema 版本说明升级

§一 五大核心"记忆"行的实现位置描述末尾追加一句：

```
memory/manager.py 当前 schema 5.8（5.0 基线 + 5.1 source_turn_idx + 5.3 priority + 5.5 archived + 5.6 title + 5.7 confidence + 5.8 last_accessed_ts LRU），
基线见 ADR-0004，5.8 LRU 增量见 ADR-0008。
```

§二 `memory/manager.py` 行注释末尾追加一句：

```
│                             # 当前 schema 5.8（v0.2.7），见 ADR-0004 + ADR-0008
```

避免每次增量都拆单行；同时兑现 ADR-0007 §2.5 留的"不在 ADR-0007 展开 5.x 全量"承诺 — 本 ADR §五 集中交代。

### D5. 顶部 ADR 链接列表加 ADR-0008

按 ADR-0007 顶部"ADR-0006 / ADR-0007"的格式追加：

```
[ADR-0007](...)（v0.3 工具面 + read_file.original_size sync）
/ [ADR-0008](adr/0008-architecture-v0-util-heartbeat-and-memory-5-8-lru.md)（v0.2.7 重做：util/heartbeat.py + memory schema 5.8 LRU；前次 commit b78638d1 被 revert）。
```

### D6. 新增约束（接 ADR-0006 D7 / ADR-0007 自检思路）

本轮 doc sync 必须额外做的 2 步自检 — **直接 grep src/ 验证**：

1. `ls src/xragent/util/*.py` 数 **模块文件**（不含 `__init__.py`），应得 6，与 doc §一"6 个模块" + §二 util/ 行注释匹配。
2. `grep -n "SCHEMA_VERSION" src/xragent/memory/manager.py` 拿 `SCHEMA_VERSION = NN`，
   doc §一 / §二正文里写的 schema 版本号应与 NN // 10 一致（`SCHEMA_VERSION = 58` ↔ schema 5.8）。

如果自检失败（例如又有人新加了 util/ 模块但忘了同步），本 ADR 的 patch 自身也要 patch 进 fix — 不留 half-applied 状态。

## 五、memory schema 5.8 LRU 增量摘要（兑现 ADR-0007 §2.5 留口）

> 本节是 ADR-0007 §2.5 明确推迟到 ADR-0008 收纳的内容。后续 5.x 增量请开 ADR-0009+。

5.8 在 5.7 之上叠加：

| 元素 | 类型 | 用途 |
|------|------|------|
| `Fact.last_accessed_ts` | `float = 0.0` | LRU 标记；`save_fact` 时初始化为 `ts`（创建即"访问"），避免新建行被 LRU 召回误伤 |
| `facts.last_accessed_ts REAL NOT NULL DEFAULT 0.0` | 列 | DB 列；`0.0` 表示"未访问过的老行"（migration 兼容） |
| `idx_facts_last_accessed_ts` | B-tree | `recall_lru` 主路径 `ORDER BY last_accessed_ts ASC LIMIT k` 直接走索引 |
| `MemoryManager.touch_fact(fact_id) -> bool` | 方法 | 刷新某条 fact 的 `last_accessed_ts` 为当前时间（标记"刚被访问"），不存在返回 `False` |
| `MemoryManager.recall_lru(k, category?, include_archived=False) -> list[Fact]` | 方法 | LRU 召回 — 按 `last_accessed_ts` ASC 取最久未访问的 top-k；可选 `category` 过滤；默认排除 archived |
| `_migrate_v57_to_v58` | migration | 幂等追加列 + 索引；不重写存量行的 `last_accessed_ts`（保持 0.0，新行由 `save_fact` 初始化） |

`SCHEMA_VERSION = 58`（即 5.8）。

5.8 配套语义：LRU 召回的语义是"**最久没被读到的事实**"，与"按时间戳排序的旧事实"不同 — 后者仍走
`memory_recall_range`，LRU 走 `recall_lru`（**还没暴露成工具**，留作 v0.4 评分基线做"长眠前先回收冷事实"用）。
本次 doc 同步**不**给 `recall_lru` 加工具表行，因为它还没注册到 `tools/registry.py`。

## 六、影响

- **代码**：零改动，纯文档同步。
- **测试**：本轮改 doc 顺手跑 `pytest -q --tb=no` 确认 0 回归（实际影响 0；所有 pre-existing fail 仍 fail 但与本轮无关）。
- **风险消除**：消除"按 doc 看到的 util/ 比实际少一个 / memory schema 版本号停在 5.0"两处失实；让未来 ADR-0009+ 接手 5.x 增量时口径统一（"5.x 全量见 ADR-0008 + 后续"）。

## 七、与被 revert 的两次落地的差异（便于 git blame 追溯）

| 项 | `b78638d1` (v0.2.7 doc, 被 `348d6f33` revert) | `b78638d1` 配套 `381c5b8b` (round 158 close-out, 被 `ed2bcb3b` revert) | ADR-0008 / 本次 |
| --- | --- | --- | --- |
| util/ 模块数表述 | "6 个模块" | 同左 | "6 个模块"（一致） |
| util/__init__.py re-export 行为 | 未明确（默认按"标准 util 包"理解） | 未明确 | **明确写"不 re-export，调用方按 from xragent.util.heartbeat import ..."**（贴合 main.py 实际用法） |
| memory schema 版本说明 | 加了"5.8 LRU"一句话但没说 ADR | 同左 | **接 ADR-0007 §2.5 留口**：§五 给"5.8 LRU 增量摘要"专表，§一 / §二正文提"schema 5.8，见 ADR-0004 + ADR-0008" |
| §五 版本对照 | 加了 v0.2.7 行 | 同左 | 加 v0.2.7 行 + **写明 commit chain（1a3d1d42 → 381c5b8b → revert → b78638d1 → revert → ADR-0008 重做）**，方便审计 |
| 自检约束 | 无 | 无 | **D6 新增**：2 步 grep 自检（util/.py 数 + SCHEMA_VERSION 比对），不达标先 patch doc 再 commit |

## 八、为什么单独留 ADR-0008 而非更新 ADR-0007

ADR-0007 §2.5 已经显式承诺"memory schema 5.x 全量说明留给 ADR-0008"；本 ADR 是兑现这条承诺，
也是把 ADR-0006 立的"v0.2.5 经历了落地 → revert → 重做" precedent 延伸到 v0.2.7。
更新 ADR-0007 会让 commit history 与"v0.2.7 也经历了落地 → revert → 重做"这件事脱钩，
不利于未来审计。单独 ADR-0008 + 引用 ADR-0006 / ADR-0007 让 git log 一眼看到
"v0.2.7 sync 也走了三事件路径"。

## 九、参考

- ADR-0001：util/ 抽取口径（"出现 2+ 次且 ≥5 行"）。
- ADR-0002：压缩 hook（react_loop.py 调 compress_if_needed）。
- ADR-0004：memory schema 5.0 基线。
- ADR-0006：v0.2.5 重做 precedent（落地 → revert → 重做三事件路径 + 自检约束 D7）。
- ADR-0007：v0.3 工具面 + read_file.original_size sync（§2.5 留口给本 ADR）。
- commit `1a3d1d42`：`util/heartbeat.py: extract duplicated heartbeat thread pattern`（**保留**）。
- commit `1b0f123c`：`feat(memory): 5.8 LRU 追踪 — last_accessed_ts + touch_fact + recall_lru`（**保留**）。
- commit `b78638d1`：v0.2.7 doc sync（被 `348d6f33` revert）。
- commit `381c5b8b`：round 158 close-out（被 `ed2bcb3b` revert）。