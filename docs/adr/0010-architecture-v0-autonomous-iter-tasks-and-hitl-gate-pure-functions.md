# ADR-0010: architecture-v0.md 同步 autonomous.iter_tasks 生成器 + hitl/gate._parse_stdin_line 纯函数化（v0.2.9）

> 状态：已采纳（v0.2.9）
> 时间：2026-07-31（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
> 上游 ADR：ADR-0009（v0.2.8：util/http_parents.py + build_default_registry）
> 涉及 commit：
>   - `7bd65f9a autonomous: 重构抽公共函数 (round 615)` — autonomous.py 抽 `task_queue_path` / `task_cooldown_key` / `_recent_titles` 三个 helper（**保留**，是 iter_tasks 落地的前置）
>   - `ecc0d468 hitl: 重构抽公共函数 (round 605)` — `hitl/gate.py` 抽 `_parse_stdin_line` 纯函数 + `_DEFAULT_POLICIES` dict（**保留**，让 stdin 解析可单测）
>   - 历史注：ADR-0009 D6 自检 `ls src/xragent/util/*.py | grep -v __init__ | wc -l` 数 7 个模块；本轮 v0.2.9 util/ 数仍是 7（两轮 refactor 都没新加 util/ 模块），证明 ADR-0008 D6 自检约束在持续生效。

## 一、背景

上一轮 ADR-0009（v0.2.8）刚把 util/ 同步到 7 个模块 + 改 `build_default_registry` 配置来源。本轮（autonomous 触发后）又发现两处新的
doc-vs-code drift，都属于"重构抽公共函数"类（同 TASK_TEMPLATES[3] 模板的产物），但发生在 **autonomous.py** 与 **hitl/gate.py** 两个
不同文件 —— 一个属"成长"核心，一个属"父母"核心。两处失实都不在 util/ 模块数（仍是 7），所以 ADR-0009 D6 自检的"模块数"那条查不出来，
需要新加一类自检："公开 API 表面扩展"。

1. **`autonomous.py` 新增公开 API `iter_tasks` 未同步**（commit `7bd65f9a autonomous: 重构抽公共函数 (round 615)`）：
   - `iter_tasks(stop_check: Callable[[], bool]) -> Iterator[dict[str, Any]]` —— **生成器**，每次 `__next__` 拉一次 `next_task()`，
     直到 `stop_check()` 返回 True 才停。
   - 配套 3 个 helper 公开化（之前是 `next_task` 体内的 inline 逻辑，现抽成模块级函数 + Google-style docstring）：
     - `task_queue_path() -> Path`（Settings.repo_root / memory / queue.jsonl）
     - `task_cooldown_key(task: dict) -> str`（取 title 作 cooldown key）
     - `_recent_titles(window_s: float = DEFAULT_COOLDOWN_S) -> set[str]`（窗口内已做 title 集合）
   - 影响面：doc §一"自驱动（autonomous）"段的实现位置描述还停在"`next_task` / `record_done` / `memory/queue.jsonl`"层；doc §二模块清单
     `autonomous.py` 行注释只写"定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl"，没有提 `iter_tasks` 这个生成器 + 3 个 helper 的公开 API 表面。
   - 测试已有覆盖：`tests/test_autonomous.py` 顶部 docstring 明列"iter_tasks：stop_check 一拉即停、且 stop_check 为 True 时不再 yield"，
     落地测试 `test_iter_tasks_yields_until_stop_check_says_stop` + `test_iter_tasks_exits_immediately_if_stop_check_true_from_start`。

2. **`hitl/gate.py` stdin 解析纯函数化未同步**（commit `ecc0d468 hitl: 重构抽公共函数 (round 605)`）：
   - **新增** `_parse_stdin_line(line: str) -> ApprovalResult` —— 纯函数，只依赖模块常量 `_APPROVE_INPUTS` / `_REJECT_INPUTS` /
     `_EDIT_PREFIX`，不读 stdin、不写 stderr，方便单测直接覆盖；行为与原 `_stdin_channel` 内 inline 解析一致。
   - **新增** `_DEFAULT_POLICIES: dict[str, Decision]` —— 把原 `_stdin_channel` 体内 2 个硬编码 `if channel_type == "stdin"` / `if channel_type == "auto_approve"` 分支
     收敛成 dict 查找（key 仍待用，比 if-elif 链可扩展）。
   - 影响面：doc §一"父母"行只写"`hitl/gate.py` + `http_server.py`"；doc §二模块清单 `hitl/gate.py` 行注释只写"HITL 门（高危动作 / 高危工具审批）"。
     都没提"stdin 解析纯函数化" + "policy dict 收敛"这两件 v0.2.9 的内部结构演进。
   - 测试覆盖（增量）：`_parse_stdin_line` 纯函数让 stdin 解析的单测从原来"必须 mock stdin"变成"直接 assert 函数返回值"，是 ADR-0001 D1
     口径"出现 2+ 次且 ≥5 行"在 hitl/gate.py 内部的具体落地（不是跨文件抽 util/，是模块内部抽纯函数；口径更松，但纯函数化的可测收益同样显著）。

两处 drift 都在 ADR-0008 D6 / ADR-0009 D6 自检约束**未覆盖**的位置（util/ 模块数 + registry 签名比对都查不到它们），本 ADR 借机扩展 D6 自检约束：
v0.2.9 起，"公开 API 表面扩展"也纳入自检（见 §四 D6）。

## 二、为什么不直接补到 ADR-0009

不能直接补到 ADR-0009，理由与 ADR-0009 §二相同（ADR 时间戳 == 决策时刻；本轮事件发生在 ADR-0009 之后；D6 自检约束按设计就该开新 ADR 响应），
外加本轮的特殊性：

1. **ADR-0009 D6 自检口径查不出来** —— util/ 模块数（仍是 7）+ `build_default_registry` 签名（仍无参）这两条都通过，但 doc 仍然过时。
   这是 ADR-0009 D6 本身的盲区（它只查 util/ + registry 两条线，没查 autonomous.py / hitl/gate.py 的公开 API 表面），
   本 ADR-0010 D6 把它扩展成"第三类自检：模块级公开函数表"（见 §四 D6）。
2. **autonomous.py 与 hitl/gate.py 属不同 五大核心** —— 一个属"成长"（autonomous.py），一个属"父母"（hitl/gate.py），按 ADR-0009 同款"两件 v0.2.x 的事"
   前例（util/http_parents.py 工具路径 + build_default_registry 工具注册）可在同一个 ADR 内并列，但要在 §四 D1-D3 把两者显式分块，避免读者混淆
   "改的是哪个文件"。
3. **不是所有 drift 都值得开 ADR** —— 这次开 ADR 是因为 `iter_tasks` 是**新公开 API**（生成器 + 3 个 helper 公开化），`_parse_stdin_line` 是**新公开纯函数**
   （HITL 门可测性结构演进），都是公开 API 表面扩展；如果是纯内部实现细节（如把 if-elif 写成 match-case），不值得开 ADR。

## 三、漂移点（code 为准）

| # | 漂移点 | 文档旧值 | 实际 | 触发 commit |
|---|--------|---------|------|------------|
| 1 | §一"自驱动（autonomous）"段 | "按 task templates + ReAct + commit 在没人在时也稳定推进的循环；模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个）" + "memory/queue.jsonl 留痕" | 模板仍是 8 个 ✅，但**公开 API 表**还多 4 个：`task_queue_path` / `task_cooldown_key` / `_recent_titles` / `iter_tasks`（其中 `iter_tasks` 是新生成器） | `7bd65f9a` round 615 |
| 2 | §二 模块清单 `autonomous.py` 行注释 | "定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl" | +`iter_tasks` 生成器 + 3 helper；新 helper 都带 Google-style docstring 与 PEP 604 类型注解 | 同上 |
| 3 | §一"父母"行 | "`hitl/gate.py` + `http_server.py`" | `hitl/gate.py` 内部结构演进：`_parse_stdin_line` 纯函数化（模块级公开 helper，不读 stdin）+ `_DEFAULT_POLICIES` dict 收敛 2 个硬编码 if 分支 | `ecc0d468` round 605 |
| 4 | §二 模块清单 `hitl/gate.py` 行注释 | "HITL 门（高危动作 / 高危工具审批）" | 同上，纯函数 + dict 收敛 | 同上 |
| 5 | §五 版本对照 | 缺 v0.2.9 | 需要补：autonomous.iter_tasks + 3 helper 公开化 + hitl/gate._parse_stdin_line 纯函数 + _DEFAULT_POLICIES dict | — |

补充说明（drift #1 + #2 备注）：

- `main.py:229` 当前用 `from .autonomous import next_task, record_done, task_queue_path`（**未导入** `iter_tasks`），主循环仍走 imperative `next_task` 路径。
  这意味着 `iter_tasks` 是**已落地但调用方未切**的公开 API —— 类似 ADR-0009 §三 drift #3 备注里 `build_default_registry` 在某段时间的
  "签名演进但调用点滞后"状态；本 ADR 不动 `main.py`，把 `iter_tasks` 的"主循环待切换"留给后续 TASK_TEMPLATES[3] 触发。
- `task_queue_path` / `task_cooldown_key` / `_recent_titles` 这 3 个 helper 的"公开化"是 `7bd65f9a` round 615 同时做的（与 `iter_tasks` 同 commit，
  同一个"重构抽公共函数" TASK_TEMPLATES 触发）；doc 现在的"next_task / record_done / memory/queue.jsonl" 是更早的描述（helper 还没抽出来时），
  是 v0.2.9 的真实 drift。

补充说明（drift #3 + #4 备注）：

- `_parse_stdin_line` 不是跨文件抽 util/，是 `hitl/gate.py` **内部**抽纯函数。理由：stdin 解析逻辑只有这一处用，不满足 ADR-0001 D1 的
  "出现 2+ 次且 ≥5 行" 跨文件口径；但同款"模块内抽纯函数"的可测收益（不需要 mock stdin，直接传字符串 → 断言返回值）足够 material，
  所以独立 commit 而不是并入其他 HITL 改动。
- `_DEFAULT_POLICIES` dict 的 key 当前仍是字面量占位（commit message 暗示后续会换成 channel_type 实例方法或 enum key），但 dict 容器本身已落地
  —— doc 同步的是"容器落地"，不是"key 终态"。后续 key 演化若再触发 doc 漂移，按 ADR-0009 D6 同款"新开 ADR"路径走。

## 四、决策

### D1. §一"自驱动（autonomous）"段加 `iter_tasks` + 3 helper 的实现位置描述

§一补充说明区第 1 条（自驱动 autonomous 段）的"模板见 TASK_TEMPLATES（共 8 个）"后面加一句公开 API 描述，从

```
- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。
```

改成

```
- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。
  公开 API：`next_task(rng)` 选一个不在 cooldown 里的任务；`record_done(task, turn_id, summary)` append-only 留痕；
  **`iter_tasks(stop_check)`** 是生成器（v0.2.9，见 ADR-0010），每次 `next()` 拉一次 `next_task()`，直到
  `stop_check()` 返回 True 才停 —— 落地测试用，main.py 主循环当前仍走 imperative `next_task` 路径（待后续切换）；
  3 个 module-level helper：`task_queue_path()` / `task_cooldown_key(task)` / `_recent_titles(window_s)`
  全部带 Google-style docstring 与 PEP 604 类型注解（v0.2.9 公开化）。
```

设计意图：

- 把 `iter_tasks` 单独加粗 + 标注 v0.2.9 + 见 ADR-0010 —— 它是本轮最 material 的新增公开 API（生成器 + 测试落地），与"3 个 helper 公开化"
  区别对待。
- "main.py 当前仍走 imperative `next_task` 路径（待后续切换）" —— 显式标注当前**未切**，避免未来读者 grep `iter_tasks` 在 main.py 找不到时误以为
  doc 错。对应 ADR-0009 §三 drift #3 备注的"`build_default_registry` 签名演进但调用点滞后"同款节奏。
- "3 个 module-level helper" 不再加粗（与 v0.2.7 + `start_heartbeat_thread` 同款轻处理；公开化但非新创）—— 节省视觉密度。

### D2. §二 模块清单 `autonomous.py` 行注释升级

§二模块清单 `autonomous.py` 行从

```
├── autonomous.py              # 定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl
```

改成

```
├── autonomous.py              # 定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl
│                             # 公开 API：next_task / record_done / iter_tasks（v0.2.9 生成器，见 ADR-0010）
│                             #          + task_queue_path / task_cooldown_key / _recent_titles（v0.2.9 公开化）
```

设计意图：

- 把"v0.2.9"标两次（生成器 + helper 公开化），与 §一 加粗的 `iter_tasks` 形成自洽。
- `iter_tasks` 在前（生成器是本轮新增），`task_queue_path` / `task_cooldown_key` / `_recent_titles` 在后（公开化但非新创）—— 与 §一 描述节奏对齐。

### D3. §一"父母"行 + §二`hitl/gate.py` 行注释加纯函数 + dict 收敛描述

§一五大核心表格的"父母"行从

```
| 父母 | `hitl/gate.py` + `http_server.py` |
```

保持不变（行长度约束），但 §一补充说明区追加一条（与 v0.2.9 的 autonomous 段并列）：

```
- **父母（HITL 门）** 内部结构：stdin 解析抽到模块级纯函数 `_parse_stdin_line(line)`（v0.2.9，见 ADR-0010），
  只依赖模块常量 `_APPROVE_INPUTS` / `_REJECT_INPUTS` / `_EDIT_PREFIX`，不读 stdin、不写 stderr；
  决策策略用 `_DEFAULT_POLICIES: dict[str, Decision]` 收敛 2 个硬编码 if 分支（v0.2.9）。
  目的：让 stdin 解析 + 决策分支**可单测**，无需 mock stdin 或 fork 子进程。
```

§二模块清单 `hitl/gate.py` 行从

```
├── hitl/gate.py               # HITL 门（高危动作 / 高危工具审批）
```

改成

```
├── hitl/gate.py               # HITL 门（高危动作 / 高危工具审批）
│                             # 内部：_parse_stdin_line 纯函数 + _DEFAULT_POLICIES dict（v0.2.9，见 ADR-0010）
```

设计意图：

- §一"父母"行的表格行**不动**（已经在 v0.2.8 + ADR-0009 期间明示过；再扩列就破表格视觉密度），把新细节塞进补充说明区（与 v0.2.9
  autonomous 段并列）；"目的：让 stdin 解析 + 决策分支**可单测**" 显式写出可测性收益，与"重构抽公共函数"的动机对齐。
- §二 `hitl/gate.py` 行注释只追加一行（"内部："），不重复 §一 已写细节，保持口径分层（§一 Why，§二 What）。

### D4. §五 版本对照加 v0.2.9 行

紧跟 v0.2.8 行后插入 v0.2.9：

```
| v0.2.9 | 架构 doc 同步：autonomous.py 加 `iter_tasks(stop_check)` 生成器（公开 API）+ 3 helper 公开化（task_queueueue_path / task_cooldown_key / _recent_titles）；hitl/gate.py 加 `_parse_stdin_line(line)` 纯函数 + `_DEFAULT_POLICIES: dict[str, Decision]` 收敛 2 个硬编码 if 分支。autonomous.py 落地 commit `7bd65f9a`；hitl/gate.py 落地 commit `ecc0d468`；本 ADR-0010 doc sync | ADR-0010 |
```

设计意图：

- 一行说清两件 v0.2.9 的事（autonomous 公开 API + hitl 内部结构），commit 引用分别列（不混在标题里），与 v0.2.7 / v0.2.8 行（同款格式）保持口径一致。
- "公开 API" / "纯函数" / "dict 收敛" 三词把本轮的两类 drift 关键词全列出来，未来 grep ADR-0010 关键词能直接定位。

### D5. 顶部 ADR 链接列表加 ADR-0010

按 ADR-0009 顶部"ADR-0008 / ADR-0009"的格式追加：

```
[ADR-0009](adr/0009-architecture-v0-util-http-parents-and-registry-settings-coupling.md)（v0.2.8：util/http_parents.py 抽取 + build_default_registry 配置来源从传参改为读 Settings） /
[ADR-0010](adr/0010-architecture-v0-autonomous-iter-tasks-and-hitl-gate-pure-functions.md)（v0.2.9：autonomous.iter_tasks 生成器 + hitl/gate._parse_stdin_line 纯函数化）。
```

设计意图：

- ADR 链接列表的顺序按 ADR 编号升序，与 §五版本对照行的 ADR 引用顺序一致；方便 git blame 时从 doc 顶部直接跳到对应 ADR。
- 简短注释里**明示**"iter_tasks 生成器 + _parse_stdin_line 纯函数化" —— 这是 §一 / §二 措辞变更的人话版 summary，对那些只看 doc 顶部不展开
  §一/§二的读者最关键。
- 用句号结尾（与 ADR-0009 注释保持一致）。

### D6. 新增约束（接 ADR-0008 D6 / ADR-0009 D6 自检思路 + 扩展"公开 API 表面"）

本轮 doc sync 必须额外做的 **4 步自检** — **直接 grep src/ 验证**（不依赖 import，避免 pre-existing 缺模块问题）：

1. `ls src/xragent/util/*.py | grep -v __init__ | wc -l` 数**模块文件**（**不含** `__init__.py`），应得 7，与 doc §一"7 个模块" + §二 util/ 行注释匹配。
   （**继承自 ADR-0009 D6-1**：本轮没新加 util/ 模块，所以这一步预期通过——如果失败，意味着有未同步的 util/ 增量，按 ADR-0009 D6 触发新 ADR。）
2. `grep -nE "^def build_default_registry\(" src/xragent/tools/registry.py` 拿函数签名，应是 `def build_default_registry() -> ToolRegistry:`（无参），
   与 doc §四不变量 line 134 改后措辞"无参调用"匹配。（**继承自 ADR-0009 D6-2**。）
3. `grep -c '^    add("' src/xragent/tools/registry.py` 数工具注册调用数，应得 17（`evolution_enabled=false` 时 unregister 2 个，剩 15），
   与 doc §二 + §三"17 个 / 15 个" 口径匹配。（**继承自 ADR-0009 D6-3**。）
4. **新增** — "公开 API 表面扩展"自检（本轮首次引入）：对每个 doc 五大核心表格引用过的 src/ 模块，用 `grep -nE "^def [a-z_]+|^    def [a-z_]+" <file>`
   拿公开函数签名表，与 doc §一/§二对该模块的描述比对：
   - `src/xragent/autonomous.py`：应得至少 7 行（`task_queue_path` / `task_cooldown_key` / `_recent_titles` / `next_task` / `record_done` / `iter_tasks`，
     加可能的 module-level helper）；与 §一"iter_tasks 生成器 + 3 helper 公开化"+ §二"autonomous.py 公开 API"行注释匹配。
     （**关键校验**：如果 grep 不到 `iter_tasks`，意味着本轮 refactor 还没落地，或 main.py 调用方已切走，doc 必须回到 v0.2.7 状态。）
   - `src/xragent/hitl/gate.py`：应得 `_parse_stdin_line` 这一行 + 既有 `ApprovalRequest` / `ApprovalResult` / `Gate` 等公开类型；与 §一补充说明区
     "_parse_stdin_line 纯函数 + _DEFAULT_POLICIES dict" + §二 hitl/gate.py "内部"行注释匹配。

如果自检失败（例如有人加了新公开 API 但忘了同步 doc，或反过来 doc 描述了不存在的 API），本 ADR 的 patch 自身也要 patch 进 fix — 不留
half-applied 状态。**这是 ADR-0009 D6 的同款约束向 v0.2.9 的延伸**：D6-4 是"ADR-0011+ 的开 ADR 触发器"，覆盖"公开 API 表面扩展"这一类之前漏掉的
drift。本轮触发器响了一次（autonomous.iter_tasks + hitl/gate._parse_stdin_line），按 D6 写新 ADR 是预期行为。

## 五、影响

- **代码**：零改动，纯文档同步。
- **测试**：本轮改 doc 顺手跑 `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no` 确认 0 回归（实际影响 0；所有 pre-existing fail 仍 fail 但与本轮无关；
  预期 autonomous.iter_tasks + hitl/gate._parse_stdin_line 增量都不引入新失败，因为它们是纯函数 / 生成器，与既有失败链 `xragent.tools.blacklist` import
  污染无交集）。

## 六、参考

- ADR-0001：util/ 抽取口径（"出现 2+ 次且 ≥5 行"）—— §一 D3 备注里说明 hitl/gate.py 的纯函数抽法不满足该口径但是模块内部抽纯函数，理由是"可测收益 material"。
- ADR-0008：v0.2.7 重做（util/heartbeat.py + memory schema 5.8 LRU）—— §四 D6 自检约束是本 ADR-0010 D6-1/2/3 的直接上游。
- ADR-0009：v0.2.8（util/http_parents.py + build_default_registry 配置来源）—— §四 D6 自检约束的扩展版（加 registry 签名比对）是本 ADR-0010 D6-1/2/3
  的直接上游；§四 D6-4 "公开 API 表面扩展" 自检是本轮首次引入，填补 ADR-0009 D6 在 autonomous.py / hitl/gate.py 上的盲区。
- commit `7bd65f9a`：`autonomous: 重构抽公共函数 (round 615)` — autonomous.py 抽 3 helper + 加 `iter_tasks` 生成器（**保留**）。
- commit `ecc0d468`：`hitl: 重构抽公共函数 (round 605)` — hitl/gate.py 抽 `_parse_stdin_line` 纯函数 + `_DEFAULT_POLICIES` dict（**保留**）。
- `src/xragent/autonomous.py` line 203：`def iter_tasks(stop_check: Callable[[], bool]) -> Iterator[dict[str, Any]]:`（新生成器，硬证据）。
- `src/xragent/autonomous.py` line 95/105/123：`task_queue_path` / `task_cooldown_key` / `_recent_titles` 三个 module-level helper（公开化）。
- `src/xragent/main.py` line 229：`from .autonomous import next_task, record_done, task_queue_path`（**未导入** `iter_tasks`，主循环待切换）。
- `src/xragent/hitl/gate.py` line 123：`def _parse_stdin_line(line: str) -> ApprovalResult:`（新纯函数，硬证据）。
- `src/xragent/hitl/gate.py` line 59：`_DEFAULT_POLICIES: dict[str, Decision] = {...}`（dict 收敛，硬证据）。
- `tests/test_autonomous.py` line 235/263：`test_iter_tasks_yields_until_stop_check_says_stop` + `test_iter_tasks_exits_immediately_if_stop_check_true_from_start`
  —— iter_tasks 行为已被测试锁定。
