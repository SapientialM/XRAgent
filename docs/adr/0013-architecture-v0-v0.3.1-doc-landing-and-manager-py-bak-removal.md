# ADR-0013: architecture-v0 v0.3.1 doc 落地 + manager.py.bak 删除回溯

- 状态：已接受
- 日期：2026-08-02
- 决策者：XRAgent（autonomous round 199）

## 背景

`docs/architecture-v0.md` 自上一轮 ADR-0011（v0.2.10 + v0.2.11 doc sync，commit 4f970a4d
被 6b7f3a99 revert 后重做）以来已积累 8 处与 `src/xragent/` 实际代码不一致：

1. **§二 `tools/registry.py` 行注释**："默认注册 17 个工具（v0.2.3 后 +1：memory_recall...
   v0.3 后 +1：memory_recall_by_tag，见 ADR-0007）" / "evolution_enabled=false 时剩 15 个"
   → 实际 `tools/registry.py::build_default_registry()` 调 `add(...)` **19 次**；
   evolution_enabled=false 时 `unregister` 后剩 **17 个**（新增 `memory_recall_by_title`
   + `memory_update_title`，见 commit `c9ea4bb9` / `213da37f`）。
2. **§二 `tools/memory_tools.py` 行注释**："5 个 memory_* 工具（save + 4 种 recall，
   见 ADR-0004 / ADR-0007）" → 实际 **7 个**（save + 5 recall + 1 update）。
3. **§二 `memory/manager.py` 行内 .bak 引用 + §二独立 `memory/manager.py.bak` 行**
   → commit `cecfef33`（CM author，2026-08-02 21:45:39 +0800，message：
   `fix(reply): restore compress_if_needed + drop manager.py.bak`）已经 `git rm` 了
   `.bak` 文件，工作区与 git tracked 都已干净。
4. **§三 注册工具表**缺 `memory_recall_by_title` + `memory_update_title` 两行。
5. **§三表底注释**："4 种 recall 风格" → 实际 **5 种**（关键词 / 时间窗 / 频次 / 标签 / title）。
6. **§四 不变量「高危工具须审批」**："剩 15 个" → 应是 17 个。
7. **§四 不变量「Memory schema 5.5 之前快照留痕」**整条 → `.bak` 已删，留痕点消失。
8. **§二模块清单**缺 `scoring/` 占位登记（**幽灵空目录**：仅 `__pycache__/`，缺
   `__init__.py`，未 git tracked，源码零引用——预留 v0.4 评分基线）。

ADR-0012 已"已接受"（commit `032d78f5`，2026-08-02 23:05:35 +0800），
**但 doc 未落地**——drift 已经发生，必须本轮一次性收口。
ADR-0012 的 D1/D2/D3/D4/D5/D6/D7 是 doc 修改的依据；本 ADR-0013 在它的基础上：

- 应用 ADR-0012 D1/D2/D3/D4/D5/D6/D7 到 architecture-v0.md；
- 新增 D8：回溯 `memory/manager.py.bak` 被 CM 删除（commit cecfef33），
  §四「schema 5.5 之前快照留痕」不变量改写为「已删，不再是留痕点」，§二模块清单
  删除对应行；
- 新增 D9：顶部 ADR 链接表补 ADR-0012 + ADR-0013；
- 新增 D10：v0.3 (planned) 行的"待办：摘要压缩 hook 强化"保持不变，v0.3.1 是
  单独的 doc-sync marker（与 ADR-0012 D7 一致）。

## 决策

### D1 — 应用 ADR-0012 D1（工具总数 17 → 19）

§二 `tools/registry.py` 行注释：

- 「默认注册 17 个工具（v0.2.3 后 +1：memory_recall，见 ADR-0004；
  v0.3 后 +1：memory_recall_by_tag，见 ADR-0007）」
  → 改为
  「默认注册 19 个工具（v0.2.3 后 +1：memory_recall，见 ADR-0004；
  v0.3 后 +1：memory_recall_by_tag，见 ADR-0007；
  v0.3.1 后 +2：memory_recall_by_title + memory_update_title，见 ADR-0012）」。
- 「evolution_enabled=false 时剩 15 个」 → 改为「剩 17 个」。

### D2 — 应用 ADR-0012 D2（§三表补 2 行）

在 `memory_recall_by_tag` 行下追加：

```
| `memory_recall_by_title`  | low | 否 | 按 title 精确匹配召回 fact（newest first），v0.3.1 上线，见 ADR-0012 |
| `memory_update_title`     | low | 否 | 更新某条 fact 的 title；new_title=None 表示清空，v0.3.1 上线，见 ADR-0012 |
```

### D3 — 应用 ADR-0012 D3（§四 剩 17 个）

§四「高危工具须审批」行：「剩 15 个」→「剩 17 个」。

### D4 — 应用 ADR-0012 D4（§二 memory_tools 行注释 7 个）

§二 `tools/memory_tools.py` 行：

- 「5 个 memory_* 工具（save + 4 种 recall，见 ADR-0004 / ADR-0007）」
  → 改为
  「7 个 memory_* 工具（save + 5 recall + 1 update，见 ADR-0004 / ADR-0007 / ADR-0012）」。

### D5 — 应用 ADR-0012 D5（§三表底注释 5 种 recall 风格）

§三表底注释：

- 「4 个 recall 工具平级，补齐 `memory_recall_by_tag` 后才是
  "4 种 recall 风格"（关键词 / 时间窗 / 频次 / 标签）」
  → 改为
  「5 个 recall 工具平级，补齐 `memory_recall_by_title` 后才是
  "5 种 recall 风格"（关键词 / 时间窗 / 频次 / 标签 / title）」。

### D6 — 应用 ADR-0012 D6（§二模块清单加 scoring/ 占位）

§二模块清单**末尾**新增一行（独立顶级包占位，不嵌任何子模块）：

```
├── scoring/                   # 占位包（v0.3.1 状态：仅 __pycache__/，缺 __init__.py，未 git tracked；
│                             #   预留 v0.4 评分基线 ROADMAP.md 用；本轮 ADR-0012 / 0013 不建不删）
```

### D7 — 应用 ADR-0012 D7（§五版本表 +v0.3.1 行）

§五版本表 v0.3 (planned) 行**之前**新增一行：

```
| v0.3.1 | 架构 doc 同步：工具面 19 个（+memory_recall_by_title +memory_update_title），
            §三表补 2 行 + §四不变量剩 17 个 + §二 memory_tools 注释 7 个 +
            §三表底 5 种 recall 风格 + §二模块清单 scoring/ 占位登记 + manager.py.bak 删除回溯。
            doc sync 落地 commit （本轮 ADR-0013）。ADR-0012 决策落地 + ADR-0013 增量。 | ADR-0012 / ADR-0013 |
```

### D8 — manager.py.bak 删除回溯（新增）

**事实**：

- commit `cecfef33`（CM author scale.chen@qq.com，2026-08-02 21:45:39 +0800）
  执行了 `delete mode 100644 src/xragent/memory/manager.py.bak`，message：
  `fix(reply): restore compress_if_needed + drop manager.py.bak`。
- 当前 `git ls-files src/xragent/memory/` 只有 `manager.py` 与 `__init__.py`。
- ADR-0011 D2 把 `.bak` 定位成"schema 5.5 之前快照 / git tracked / 当前不被 import /
  清理决策留给后续轮次"——commit cecfef33 是 CM 主动清理，**实际发生**。

**决策**：

- §二模块清单**删除**：
  ```
  ├── memory/manager.py.bak      # schema 5.5 之前快照（git tracked，round 147 commit 43f68ada，
                                #   不被 import；清理决策留给后续轮次，见 ADR-0011 D2）
  ```
- §二 `memory/manager.py` 行内 .bak 注释删除：
  ```
  │                             #   ── v0.2.10 留痕：schema 5.5 之前快照
  │                             #     memory/manager.py.bak（git tracked，commit 43f68ada），
  │                             #     当前不被 import，清理决策留给后续轮次（见 ADR-0011 D2）
  ```
  → 整段删除（不留 fallback 注释，保持 module 注释干净）。
- §四不变量表**删除**整行：
  ```
  | Memory schema 5.5 之前快照留痕 | `memory/manager.py.bak` v0.2.10 起：git tracked（commit 43f68ada），当前不被 import，仅作 schema 演进回溯点；清理决策留给后续轮次（见 ADR-0011 D2） |
  ```
- §五版本表 v0.2.10 行内 "memory/manager.py.bak 留痕（schema 5.5 之前快照，git tracked 不被 import）"
  修订为 "memory/manager.py.bak 留痕**（commit 43f68ada）→ 后续 CM commit `cecfef33`
  `git rm` 主动清理**"。v0.2.10 行的 4 个 doc sync 主题保留其他 3 个
  （registry 内部结构 / `__tools_probe__.txt` 留痕 / `compression/hook.py` import 整理）。

**理由**：

- **doc 不写与现状冲突的话**——5 处引用 `.bak` 作为"git tracked 留痕点"，
  而现状是 commit cecfef33 已 `git rm`，新读者 `git ls-files` 会找不到，
  与 doc 描述的"v0.2.10 起 git tracked"相反。
- **CM 手动决策不应被默默埋掉**——commit cecfef33 是 CM author（不是 autonomous），
  message 明确说"drop manager.py.bak"，是显式清理 ADR-0011 D2 留给后续轮次的"清理决策"。
  doc 同步应该记录这一动作，而不是让 `.bak` 在 doc 里继续"留痕"。
- **不留删 fallback 注释**——`manager.py` 是当前活的源文件，注释里写"5.5 之前快照
  留痕"已经过期；保留会引入新的内部不一致。

### D9 — 顶部 ADR 链接表补 ADR-0012 + ADR-0013（新增）

顶部"完整方案…"段后追加两行：

```
> [ADR-0012](adr/0012-architecture-v0-doc-sync-tool-count-and-scoring.md)（v0.3.1：
> 工具面 17 → 19 + §三表补 2 行 + §四剩 17 + §二 memory_tools 7 个 + §三表底 5 种 recall +
> §二模块清单 scoring/ 占位登记；commit `032d78f5`）。
> [ADR-0013](adr/0013-architecture-v0-v0.3.1-doc-landing-and-manager-py-bak-removal.md)
> （v0.3.1 doc sync 落地：应用 ADR-0012 所有 D1-D7 + manager.py.bak 删除回溯 D8）。
```

放在 ADR-0011 行后。

## 影响面

- **architecture-v0.md**：8 处修改（D1 工具数 + D2 表 +2 行 + D3 §四剩 17 + D4 注释 7 个
  + D5 §三表底 5 种 + D6 scoring/ 占位 + D7 v0.3.1 版本行 + D8 .bak 删除回溯 5 处）；
  D9 顶部 ADR 链接表 +2。
- **源码**：**不动**——纯 doc sync。
- **测试**：**不动**——pytest 跑 `tests/`，docs 改动不触任何 .py。
- **diary**：本轮跑完后会自然 append 一段（与往常一样，不属本 ADR 范围）。

## 反向兼容

- D1 工具数 17 → 19 是**追加**——既有 17 个工具的 LLM 契约（specs() 表）没改名 /
  没改风险档位 / 没改 HITL 状态；只是新增 2 个 low 风险工具。
- D6 scoring/ 占位登记是**纯 doc**，不引入新 src/ 文件，不改任何 import 链。
- D8 .bak 删除**只删 doc 引用**——commit cecfef33 已经物理删除 .bak，本 ADR 同步
  doc 而已，不二次删除。

## 后续待办（非本轮）

- `tools/memory_tools.py` 顶部注释还写"3 个 recall 风格工具"，下次 refactor 时
  顺手改为 5 个（沿用 ADR-0012 D5 的"非本轮"待办）；
- v0.4 评分基线落地时写 `src/xragent/scoring/__init__.py` + 真模块，把 D6 占位
  换成实际占位符（沿用 ADR-0012 D6 的"非本轮"待办）；
- v0.3 (planned) 行的"摘要压缩 hook 强化"待办**不变**——本轮是 doc sync，不是功能落地。

## 决策追踪

| 时间 | 事件 |
| --- | --- |
| 2026-08-02 21:45:39 +0800 | CM commit `cecfef33` `git rm` `manager.py.bak` |
| 2026-08-02 23:05:35 +0800 | autonomous commit `032d78f5` 写 ADR-0012（doc 未落地） |
| 2026-08-02（本轮） | autonomous round 199 写 ADR-0013 + 改 architecture-v0.md（doc 落地） |