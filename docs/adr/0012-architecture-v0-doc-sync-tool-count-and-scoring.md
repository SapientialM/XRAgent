# ADR-0012: architecture-v0 doc 同步 — 工具数 17 → 19 + scoring/ 目录登记

- 状态：已接受（v0.3.1 doc sync）
- 日期：2026-08-02
- 决策者：XRAgent（autonomous round）

## 背景

`docs/architecture-v0.md` 与 `src/xragent/` 实际代码出现 5 处不一致（与 code 对照，**code 为准**）：

1. **工具总数**写"17 个 / evolution_enabled=false 时 15 个"，实际 `tools/registry.py::build_default_registry()` 注册 **19 个**，evolution_enabled=false 时剩 **17 个**（去 `propose_self_replace` + `terminate`）。
2. **§三 工具表**缺 `memory_recall_by_title` + `memory_update_title` 两行。
3. **§二 `tools/memory_tools.py` 行**注释写"5 个 memory_* 工具（save + 4 种 recall）"，实际是 **7 个**（save + 5 recall + 1 update）。
4. **§三表底**注释"4 种 recall 风格"，实际 **5 种**（关键词 / 时间窗 / 频次 / 标签 / title）。
5. **`src/xragent/scoring/`** 目录在仓库里实存（仅 `__pycache__/`，缺 `__init__.py`，**未 git tracked**），architecture-v0.md §二模块清单完全未提及。

根因：ADR-0007（v0.2.6）后 commit `c9ea4bb9` / `213da37f` / `43f68ada` / `91ea0843` / `65b75fae`
陆续在 `tools/registry.py` 加了 `memory_recall_by_title` + `memory_update_title` 两个 low 风险工具，
并在 `src/xragent/scoring/` 留过 transient 探针（git 已 untracked），但**没触发新一轮 doc sync**。
ADR-0007 → ADR-0011 共 4 轮 ADR 都聚焦在 registry 内部结构 / memory schema 5.8 / util 抽取，
没人回头补"实际注册表里多了 2 个工具"这件事实。

## 决策

### D1 — 工具总数 17 → 19

**事实**：`tools/registry.py::build_default_registry()` 内 `add(...)` 调用共 19 次（low 10 + medium 3 + high 6）；
evolution_enabled=false 时 `r.unregister("propose_self_replace")` + `r.unregister("terminate")` 后剩 17 个。

**决策**：architecture-v0.md §二 `tools/registry.py` 行注释
「默认注册 17 个工具（v0.2.3 后 +1：memory_recall...」→ 改为
「默认注册 19 个工具（v0.2.3 后 +1：memory_recall，见 ADR-0004；
v0.3 后 +1：memory_recall_by_tag，见 ADR-0007；
**v0.3.1 后 +2：memory_recall_by_title + memory_update_title，见 ADR-0012**）」。

同时把「evolution_enabled=false 时剩 15 个」→ 17 个。

**理由**：这两个数字是 LLM-facing 契约的一部分——`ToolRegistry.specs()` 直接喂给 LLM，
LLM 看 `len(specs())` 决定调用哪个工具；doc 与代码不一致 = LLM 工具描述表不一致。

### D2 — §三 工具表补 2 行

**事实**：`memory_recall_by_title` + `memory_update_title` 是 `tools/memory_tools.py` 实际存在的两个
低风险 LLM 工具，但 §三 注册工具表完全没列。

**决策**：在 §三 表里 `memory_recall_by_tag` 行下追加两行：

```
| `memory_recall_by_title`  | low | 否 | 按 title 精确匹配召回 fact（newest first），v0.3.1 上线，见 ADR-0012 |
| `memory_update_title`     | low | 否 | 更新某条 fact 的 title；new_title=None 表示清空，v0.3.1 上线，见 ADR-0012 |
```

**理由**：§三是父母 / 新读者看「当前 LLM 实际能用哪些工具」的唯一入口；缺两行 = 工具能力
对父母不可见，未来 parents 想 "更新一条事实的 title" 时不知道有现成工具，
会要求 Agent 写新代码绕过 `memory_update_title`。

### D3 — §四「高危工具须审批」不变量数字同步

**事实**：§四表里写 `False` 时 unregister `propose_self_replace` + `terminate`（剩 15 个），
应是 17 个。

**决策**：改为「剩 17 个」。

**理由**：与 D1 同构——15 vs 17 决定父母读 doc 时以为"少 4 个工具"，实际是"少 2 个"，
会低估 high-risk 通道的覆盖度。

### D4 — §二 `tools/memory_tools.py` 行注释数字同步

**事实**：doc 写「5 个 memory_* 工具（save + 4 种 recall）」，实际：

  * save 1：`memory_save`
  * recall 5：`memory_recall` / `memory_recall_range` / `memory_top_frequent` /
    `memory_recall_by_tag` / `memory_recall_by_title`
  * update 1：`memory_update_title`

共 7 个。

**决策**：改为「7 个 memory_* 工具（save + 5 recall + 1 update，见 ADR-0004 / ADR-0007 / **ADR-0012**）」。

**理由**：与 §三表 / 工具总数三处必须一致（doc 内部一致性也是契约的一部分）。

### D5 — §三表底注释「4 种 recall 风格」→ 5 种

**事实**：原注释说"`memory_recall_by_tag` 后才是"4 种 recall 风格""，
实际当前 5 种：关键词 / 时间窗 / 频次 / 标签 / title。

**决策**：改为「5 种 recall 风格（关键词 / 时间窗 / 频次 / 标签 / title）」，
并把句尾"memory_tools.py 注释里也明说"保留（`tools/memory_tools.py` 顶部注释
目前还说"3 个 recall 风格工具"，本次**不修改源码**——下次 refactor 时一起改注释即可）。

**理由**：doc 自己内部数字不一致是 hard error；源码注释可下次顺手。

### D6 — `src/xragent/scoring/` 目录登记（不删不建）

**事实**：
- `list_dir src/xragent/scoring/` 只显示 `__pycache__/`
- `read_file src/xragent/scoring/__init__.py` 失败（No such file）
- `git ls-files src/xragent/scoring` 完全为空 → 没有任何文件被 git tracked
- `grep -rn "scoring" src/xragent/` 仅命中 `__pycache__/*.pyc` 二进制，无任何 `.py` 引用

→ 这是个"幽灵空目录"：源码不引用、git 不跟踪、`__init__.py` 缺，仅 `__pycache__/` 里有
历史编译产物（被 .gitignore 默认忽略）。

**决策**：architecture-v0.md §二模块清单**末尾**新增一行 placeholder（不在任何子模块下，
因为它本身是预留顶级包占位）：

```
├── scoring/                   # 占位包（v0.3.1 状态：仅 __pycache__/，缺 __init__.py，未 git tracked；
│                             #   预留 v0.4 评分基线 ROADMAP.md 用；本轮 ADR-0012 不建不删）
```

**理由**：
- 不建 `__init__.py`：本轮指令明确"改 docs/ + 加 ADR"，未授权 src/ 改动；
  建 `__init__.py` 等于越界触发器（autonomous.py 触发器对 src/ 改动敏感，docs-only
  是预期路径）。
- 不 `git rm` 整个目录：目录本身就不在 git 里（`git ls-files` 为空），
  `git rm` 无目标可删；保留物理目录对齐 ROADMAP.md v0.4「评分基线」预留位。
- doc 里登记 = "未来新读者 `ls` 看到这个空目录不会再问"。

### D7 — §五 版本对照表新增 v0.3.1 行

**事实**：v0.3 行写的是 `planned`，v0.3.1 是本次 doc sync 的落地版本。

**决策**：在 §五 表 v0.3 (planned) 行**之前**新增一行：

```
| v0.3.1 | 架构 doc 同步：工具面 19 个（+memory_recall_by_title +memory_update_title），
            §三表补 2 行 + §四不变量剩 17 个 + §二 memory_tools 注释 7 个 +
            §三表底 5 种 recall 风格 + §二模块清单 scoring/ 占位登记。
            落地 commit （本轮）；本 ADR-0012 doc sync | ADR-0012 |
```

**理由**：版本对照表是 ROADMAP.md ↔ architecture-v0.md 的桥；
v0.3 (planned) 还没勾，v0.3.1 是为本次单独增量留的 marker。

## 影响面

- **architecture-v0.md**：改 §二模块清单（registry / memory_tools / 加 scoring/）、§三工具表（+2 行）、§四不变量（15→17）、§五版本表（+v0.3.1 行）、顶部 ADR 链接（+0012）。
- **源码**：**不动**——纯 doc sync。
- **测试**：**不动**——pytest 跑 `tests/`，docs 改动不触任何 .py。
- **diary**：本轮跑完后会自然 append 一段（与往常一样，不属本 ADR 范围）。

## 反向兼容

- D1 工具数 17 → 19 是**追加**，不是替换——既有 15 个工具的 LLM 契约（含 evolution_enabled=false
  时剩 13 个）已经被 ADR-0011 §三表锁过，**没有任何既有工具改名 / 改风险档位 / 改 HITL 状态**。
- D6 scoring/ 占位登记是**纯 doc**，不引入新 src/ 文件，不改任何 import 链。

## 后续待办（非本轮）

- 下一轮 refactor 时顺手把 `tools/memory_tools.py` 顶部注释「3 个 recall 风格工具」改为 5 个；
- v0.4 评分基线落地时写 `src/xragent/scoring/__init__.py` + 真模块，把 D6 占位换成实际占位符；
- ADR-0007 / ADR-0011 §三表 / §四不变量里的旧数字（17 / 15）本次已同步，无需二次 sync。