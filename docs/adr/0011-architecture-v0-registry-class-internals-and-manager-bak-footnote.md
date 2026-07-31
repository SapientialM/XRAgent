# ADR-0011: architecture-v0.md 同步 tools/registry.py 内部结构展开 + memory/manager.py.bak 备份留痕（v0.2.10）

> 状态：已采纳（v0.2.10）
> 时间：2026-07-31（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/，找 doc-vs-code drift"
> 上游 ADR：ADR-0010（v0.2.9：autonomous.iter_tasks 生成器 + hitl/gate._parse_stdin_line 纯函数化）
> 涉及 commit：`061fe162`（ToolRegistry API docstring 化）/ `bc097ae4`（get NameError 修复）/
> `28c9e221`（抽 `_apply_hitl` HITL dispatch）/ `c9ea4bb9`（抽 `_safe_call` 收异常契约）/
> `43f68ada`（引入 `memory/manager.py.bak` 备份）/ `91ea0843`（min_diff_bytes gate 同期产物 `__tools_probe__.txt`）

## 一、背景

ADR-0010 D6-4 自检约束（"公开 API 表面扩展"）首次引入的目的是把 autonomous.py / hitl/gate.py drift 抓出来——本 ADR-0011 是该约束
触发的**第二例**（也是 registry.py 这一线的首例）。本轮触发 D6-4 自检的具体路径是 `TASK_TEMPLATES[6]`，按 ADR-0010 D6-4 设计预期开新 ADR。

本轮 drift 分两类：

1. **公开 API 表面扩展（registry.py 内部结构）**：ADR-0010 落地时 v0.2.9 doc §二 `tools/registry.py` 行注释只写了 "build_default_registry()：
   注册 17 个工具"，把 registry.py 当成"1 个工厂函数"的薄壳。但实际上 registry.py 在 v0.1 出生（`8f72acd5`）后经历了 4 轮 refactor
   （HITL dispatch 抽取 / NameError 修复 / ToolRegistry class 公开 API 化 / `_safe_call` 抽取），已从"工厂函数"演化成"完整的工具注册
   中心"——`ToolDef` dataclass + `ToolRegistry` class 六方法 + 5 个 module-level HITL/异常 helper（`_HitlRejected` / `_HitlOutcome` /
   `_call_gate` / `_apply_hitl` / `_safe_call`）。影响面：doc §二行注释长度比 `autonomous.py` / `hitl/gate.py` 都短（3 行 vs. 4 行），
   未提 `ToolDef` / `ToolRegistry` / `_safe_call` / `_apply_hitl` 任一名字。

2. **仓库残留文件无 doc 化（manager.py.bak + __tools_probe__.txt）**：
   - `src/xragent/memory/manager.py.bak`（2832 bytes）：commit `43f68ada autonomous: 改进 memory (round 147)` 引入，schema 5.5 之前
     快照（`Fact` 只有 `id/ts/category/content/source_turn` 五字段，没 `priority` / `archived` / `title` / `confidence` /
     `last_accessed_ts`），**git tracked**（`.gitignore` 不含 `*.bak`）。
   - `src/xragent/__tools_probe__.txt`（45 bytes）：内容 `probe 1785260823 — diagnostic for write_file`，疑似 v0.1.2 时期
     `min_diff_bytes` gate 测 write_file 的探针残留（commit `91ea0843` 同期），**git tracked**。
   - 影响面：doc §二模块清单完全没提这两文件存在。本 ADR 不动文件本身，只 doc 化"存在且有意保留"，把清理决策留给后续轮次。

## 二、为什么不直接补到 ADR-0010

不能直接补到 ADR-0010，理由与 ADR-0008 → ADR-0009 → ADR-0010 同款（ADR 时间戳 == 决策时刻），外加本轮特殊性：

1. **ADR-0010 D6-4 自检设计预期就是开新 ADR**——D6-4 文末明说"本轮触发器响了一次（autonomous.iter_tasks + hitl/gate._parse_stdin_line），
   按 D6 写新 ADR 是预期行为"。本轮是 D6-4 的**第二次**响应（registry.py + 仓库残留），与"开新 ADR"的设计口径一致；塞回 ADR-0010
   会破 D6-4 自身约束。
2. **registry.py 演进历史比 autonomous.py / hitl/gate.py 复杂**——涉及 5 个 commit（出生 + 4 轮 refactor），每轮语义独立。在
   ADR-0010 内简略带过会丢 commit 引用，不符合 ADR-0009 §六的"硬证据 + commit 引用"惯例。
3. **仓库残留文件是独立 drift 类别**——不属于"公开 API 表面扩展"，是"doc 没记的仓库残留"。本 ADR 借机把约束扩到 D6-5（仓库残留
   文件清单）。

## 三、漂移点（code 为准）

| # | 漂移点 | 文档旧值 | 实际 | 触发 commit |
|---|--------|---------|------|------------|
| 1 | §二 `tools/registry.py` 行注释 | "build_default_registry()：注册 17 个工具"（3 行） | 见 D1 展开（11 行，含 ToolDef + ToolRegistry 六方法 + 5 helper） | `8f72acd5` + `28c9e221` + `bc097ae4` + `061fe162` + `c9ea4bb9` |
| 2 | §二 `memory/manager.py` 行注释 | MemoryManager + schema 5.8（v0.2.7） | 同左 ✅，但**同目录**还有 `manager.py.bak`（schema 5.5 之前快照） | `43f68ada` |
| 3 | §二 `src/xragent/__tools_probe__.txt` | 完全没列 | 文件存在（45 bytes，content 见 §一），git tracked | `91ea0843` 同期 |
| 4 | §五版本对照 | 缺 v0.2.10 | 需补：registry.py 内部结构 doc 展开 + 两文件留痕 | — |

补充（drift #1 备注）：

- `_safe_call` 契约：handler 抛 `Exception` 时返回 `{"ok": False, "error": "<TypeName>: <msg>"}` envelope；`BaseException`
  （`KeyboardInterrupt` / `SystemExit`）不吞让 supervisor 接管。doc §三工具表格不展开 envelope 契约（§三口径是工具表）；
  envelope 详细契约在 `registry.py` 自身 docstring 里。
- `ToolRegistry.run` 流程：HITL gate → `_apply_hitl` 决定 args/approved/rejected → rejected 走 `blocked_by: "hitl"` envelope →
  否则 `_safe_call(handler, args)` → approved 时结果 dict 加 `hitl_approved: True`。
- `_apply_hitl` + `_call_gate` 是 ADR-0009 D6 之后被本轮首次覆盖的内容（ADR-0009 当时只对比 `build_default_registry` 签名，
  没比对 registry 内部 helper 数）；本 ADR 借机把 helper 数也纳入 D6 自检（见 §四 D6-4）。

补充（drift #2 + #3 备注）：

- 两文件当前**都不被 import**（`grep -rn "manager.py.bak\|__tools_probe__" src/ tests/` 预期 0 hit，待 D6-5 验证）。
- `manager.py.bak` 保留理由（推测）：schema 5.5→5.8 演进前快照，未来做 schema migration 回滚验证可当 reference。
- `__tools_probe__.txt` 出现在 `src/` 根目录下有点违和。本 ADR 不清理两文件，决策留给后续轮次。
- `.gitignore` 不含 `*.bak` / `*probe*`——本 ADR 不改 `.gitignore`（黑名单，会触发 supervisor 自愈链）。

## 四、决策

### D1. §二 `tools/registry.py` 行注释展开内部结构

```
├── tools/registry.py          # build_default_registry()：注册 17 个工具
│                             # （v0.2.3 后 +1：memory_recall，见 ADR-0004；
│                             #  v0.3 后 +1：memory_recall_by_tag，见 ADR-0007）
│                             # evolution_enabled=false 时剩 15 个（去 propose_self_replace + terminate）
│                             # 内部（v0.2.10，见 ADR-0011）：
│                             #   - ToolDef dataclass（name/description/input_schema/risk/handler）
│                             #   - ToolRegistry class：register / unregister / get / names / specs / run
│                             #     run 流程：HITL gate → _apply_hitl → rejected 走 blocked envelope
│                             #               → 否则 _safe_call(handler, args) 包异常 → approved 加 hitl_approved: True
│                             #   - _apply_hitl：决策 args/approved/rejected（高风险走 HITL，return ApprovalRequest）
│                             #   - _safe_call：handler 异常统一包 {"ok": False, "error": "<TypeName>: <msg>"} envelope；
│                             #     BaseException（KeyboardInterrupt / SystemExit）不吞，让 supervisor 接管
│                             #   - _call_gate：兼容 callable gate 与 .request() 对象两种 HITL gate 形态
│                             #   - _HitlRejected sentinel + _HitlOutcome NamedTuple
```

行注释从 3 行扩到 11 行，反映 registry.py 从"工厂函数薄壳"演化成"工具注册中心"的真实形态。
README `## 🗂 Project Layout` 段同步展开（见 D5）。

### D2. §二新增 `memory/manager.py.bak` 备份留痕

```
├── memory/manager.py          # MemoryManager：SQLite 长期事实 + compress_if_needed 封装
│                             # 当前 schema 5.8（v0.2.7），见 ADR-0004 + ADR-0008
│                             # 同目录 manager.py.bak：schema 5.5 之前快照（round 147，commit 43f68ada），
│                             # git tracked；当前不被 import，清理决策留给后续轮次
```

### D3. §二新增 `src/xragent/__tools_probe__.txt` 探针残留留痕

```
├── __tools_probe__.txt        # 45 bytes 探针残留（疑似 min_diff_bytes gate 测试产物，commit 91ea0843 同期），
│                             # git tracked；当前不被 import，清理决策留给后续轮次
```

### D4. §五版本对照补 v0.2.10

```
| v0.2.10 | docs/adr/0011 + docs/architecture-v0.md §二 | registry.py 内部结构 doc 展开（ToolDef + ToolRegistry class + _safe_call / _apply_hitl / _HitlOutcome）；manager.py.bak 备份留痕；__tools_probe__.txt 探针残留留痕；D6-5 自检新增 |
```

### D5. README.md 模块清单同步

README.md `## 🗂 Project Layout` 段同步展开 `tools/registry.py` 行注释（与 §二一致）。

### D6. D6-5 自检新增：仓库残留文件清单

ADR-0008 → ADR-0009 → ADR-0010 累积的 D6 自检覆盖 4 类：D6-1 util/ 模块数 / D6-2 `build_default_registry()` 签名 /
D6-3 `registry.add(...)` 调用次数 / D6-4 模块级公开函数表。本 ADR 新增 **D6-5：仓库残留文件清单**——每次开 architecture-v0 同步类
ADR，必须 `git ls-files src/` 与 doc §二模块清单对比，识别"git tracked 但 doc 没列"的文件并在 ADR 表格单独成行；清理动作由后续
轮次决定。本轮 D6-5 覆盖：`manager.py.bak` + `__tools_probe__.txt`。

## 五、约束

- 本 ADR 不修改任何 src/ 代码或 .gitignore（黑名单），仅修改 docs/ + README.md。
- 不删 `manager.py.bak` 或 `__tools_probe__.txt`，只 doc 化存在。
- 不展开 envelope 形状到 §三（口径是工具表）；envelope 详细契约在 `registry.py` docstring 里。

## 六、自检

### 6.1 D1/D2/D3 落地校验

读 architecture-v0.md §二，确认 `tools/registry.py` 行注释包含 ToolDef / ToolRegistry / _safe_call / _apply_hitl / _HitlOutcome
全部 5 个名字；`memory/manager.py` 行注释提到 manager.py.bak（"schema 5.5 之前快照 / round 147"）；根目录 `__tools_probe__.txt`
行注释存在（"min_diff_bytes gate 测试产物 / commit 91ea0843"）。

### 6.2 D4 落地校验

读 architecture-v0.md §五版本对照表，确认 v0.2.10 行存在且文案与本 ADR §四 D4 一致。

### 6.3 D5 落地校验

读 README.md `## 🗂 Project Layout`，确认 `tools/` 行注释至少点名 ToolRegistry（README 是开发者快速入口，
格式是单行 parenthesized，不展开内部结构；完整 ToolDef + ToolRegistry 六方法 + 5 helper 在 architecture-v0.md §二）。
允许的形式：`registry.ToolRegistry + 17 工具 + blacklist；内部展开见 ADR-0011`。

### 6.4 D6-5 残留文件校验

跑 `git ls-files src/xragent/`，与 doc §二对比：`manager.py.bak` ✅ / `__tools_probe__.txt` ✅ / 其他未在 doc 出现的 git tracked
文件必须 0 个（除已列 .py）。

### 6.5 跨文件一致性

`grep -rn "manager.py.bak" docs/` 应 ≥ 2 hit（§二 + ADR-0011）；`grep -rn "__tools_probe__.txt" docs/` 应 ≥ 2 hit；`grep -n
"ToolDef\|ToolRegistry\|_safe_call\|_apply_hitl" docs/architecture-v0.md` 应 ≥ 5 hit。

## 七、影响

- 后续 round 触发 TASK_TEMPLATES[6] 时，doc §二与 src/ 实际形态差距缩小（registry.py 内部不再是盲区）；残留文件显式记入 doc 后，
  autonomous 不会再"看到 .bak 困惑要不要删"。
- §三工具表格不变（envelope 契约属 registry 内部）；§四不变量不变（高危审批门是 §四的事）。
- D6-5 自检约束从此是 autonomous 任务模板的一部分，所有 architecture-v0 同步类 ADR 都要做残留文件扫描。

## 八、引用

- ADR-0010 §四 D6-4（公开 API 表面自检）—— 本 ADR 是 D6-4 第二次响应
- ADR-0009 §六（硬证据 + commit 引用惯例）—— 本 ADR §三表格遵循
- ADR-0008 §四 D5（新增 ADR vs. 补旧 ADR）—— 本 ADR §二遵循
- 触发 commit：`061fe162` / `bc097ae4` / `28c9e221` / `c9ea4bb9` / `43f68ada` / `91ea0843`