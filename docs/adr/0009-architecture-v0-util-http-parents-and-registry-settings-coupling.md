# ADR-0009: architecture-v0.md 同步 util/http_parents.py（6 → 7 模块）+ build_default_registry 签名演进（v0.2.8）

> 状态：已采纳（v0.2.8）
> 时间：2026-07-31（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
> 上游 ADR：ADR-0001（util/ 抽取口径）/ ADR-0006（v0.2.5 重做）/ ADR-0008（v0.2.7 重做）
> 涉及 commit：
>   - `7bd65f9a autonomous: 重构抽公共函数 (round 615)` — util/http_parents.py 抽取（**保留**，是 util/ 7 号模块的真正落地）
>   - 历史注：ADR-0008 D6 自检 `ls src/xragent/util/*.py` 数 6 个模块；本轮 round 615 后该自检会数到 7 个，证明 ADR-0008 的自检约束本身在保护后续 doc sync 不漂移

## 一、背景

上一轮 ADR-0008（v0.2.7）刚把 util/ 同步到 6 个模块（+heartbeat.py），§五版本对照封顶到 v0.2.7。但代码侧在
ADR-0008 落地后又继续推进，本轮（autonomous round 615 触发后）发现两处新的 doc-vs-code drift：

1. **`util/http_parents.py` 新模块未同步**（commit `7bd65f9a autonomous: 重构抽公共函数 (round 615)`）：
   `main.py::cmd_interactive` 的 `if with_http` 分支和 `main.py::cmd_autonomous` 的 HTTP server 启动段是同一段
   6+ 行模板（`from .http_server import register_answer_sink, register_input_queue, start_server_background` + `last_answer_box`
   字典构造 + 三次 register + `start_server_background(loop)` + `print(f"[…] HTTP on …")`）。round 615 把它抽成
   `util/http_parents.py::setup_http_parents_channel(...)`，两处调用点各塌成 3-4 行。但 doc §一正文 / §二模块清单
   还停在 6 个模块（ADR-0008 状态），§五版本对照也缺 v0.2.8。

2. **`build_default_registry()` 签名演进未同步**：
   - 旧：`build_default_registry(evolution_enabled=True/False)` — 调用方显式传参
   - 新：`build_default_registry()` — 不接参数，从 `config.settings.Settings.evolution_enabled` 自动读取
   - 改动证据：`tools/registry.py` 第 161 行 `def build_default_registry() -> ToolRegistry:`（无参数），
     第 273-275 行 `s = get_settings(); if not s.evolution_enabled: r.unregister(...)`，注册语义没变（仍 unregister
     `propose_self_replace` + `terminate`），但**配置来源从"调用方注入"变成"settings 自读"**。
   - 影响面：§四不变量表格里 "高危工具须审批" 行（line 131）的实现位置描述还写
     "`build_default_registry` 传 `evolution_enabled` 决定 evolution_tools 是否注册"，已与实际不符；
     调用点 `react_loop.py:179 self.registry = registry or build_default_registry()` 也是无参调用。

两处失实都在 ADR-0008 D6 自检约束覆盖范围内（util/.py 数 + 函数签名比对），但 ADR-0008 落地时这两个 drift 都还**没发生**
—— `7bd65f9a` 是 ADR-0008 之后的 commit，registry 签名变化也是同段时间由其他 typing/refactor commit 顺手清掉的（具体见 §三 drift #2 备注）。
本轮是 v0.2.8 第一次 doc sync，按 ADR-0008 立的前例走"落地 → ADR → patch"三步路径。

## 二、为什么不直接补到 ADR-0008

不能直接补到 ADR-0008，原因：

1. **ADR-0008 的时间戳是 v0.2.7**：ADR-0008 §一开头写明"v0.2.7 在 src/ 侧实际落地了两件事"。把 v0.2.8 的两件新事塞回
   v0.2.7 的 ADR，违反"ADR 时间戳 == 决策时刻"原则，未来 git blame 会出现"为什么 v0.2.7 的 ADR 里写着 v0.2.8 的事"的歧义。
2. **ADR-0008 的 D6 自检约束已经覆盖到本轮**：ADR-0008 §四 D6 说"如果自检失败（例如又有人新加了 util/ 模块但忘了同步），
   本 ADR 的 patch 自身也要 patch 进 fix — 不留 half-applied 状态"。这意味着后续 util/ 增量**不需要**回 ADR-0008 patch，
   而是**新开 ADR-0009+** 把新增同步进来 — D6 是"ADR-0009+ 的开 ADR 触发器"，不是"回到 ADR-0008 补"。
3. **registry 签名演进属 v0.2.8 的独立事件**：签名变化是 typing/refactor pass 的副产物，发生在 util/http_parents.py 抽取
   前后一段时间里，不属于 util/ 模块数变化的一部分。本 ADR 把它单独列决策 D3，避免把"util/ 计数 + registry 配置来源"
   两件不同性质的事混在一段改动里。

## 三、漂移点（code 为准）

| # | 漂移点 | 文档旧值 | 实际 | 触发 commit |
|---|--------|---------|------|------------|
| 1 | §一 util/ 注释 | "当前 6 个模块：`json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat`" | **7 个**：再加 `http_parents.py` (`setup_http_parents_channel`) | `7bd65f9a` round 615 |
| 2 | §二 util/ 行注释 + 清单 | "6 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat" | **7 个** | 同上 |
| 3 | §四不变量"高危工具须审批"行 | "`build_default_registry` 传 `evolution_enabled` 决定 evolution_tools 是否注册" | `build_default_registry()` 不接参数；从 `Settings.evolution_enabled` 自动读，`if not s.evolution_enabled: r.unregister(...)` | registry.py 签名演进（与 typing/refactor pass 同时段） |
| 4 | §五 版本对照 | 缺 v0.2.8 | 需要补：util/http_parents.py 抽取 + registry 配置来源变化（ADR-0009） | — |

补充说明（drift #3 备注）：

- `build_default_registry` 在 git history 里曾有过带 `evolution_enabled` 参数的签名（早期阶段允许调用方注入开关，方便测试），
  后被 typing/refactor pass 顺手收掉，统一改为"读 settings"。§二模块清单里 `tools/registry.py` 行的注释
  ("evolution_enabled=false 时剩 15 个") 措辞仍然准确（语义对，只是来源从"传参"变成"自读"），本 ADR 不动它，只动 §四。
- `react_loop.py:179` 当前调用 `build_default_registry()` 无参，与新签名一致；这是 §四 line 131 措辞必须改的硬证据。

## 四、决策

### D1. §一正文 util/ 注释升级 6 → 7

把 §一 util/ 注释段从

```
当前 6 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` / `heartbeat`
（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008）。
`heartbeat.py::start_heartbeat_thread(stop_predicate, interval_s, name)` 把 main.py 中
两处重复的 7 行 `while not <stop>: try: rs.heartbeat(); except: pass; wait(<interval>)`
模板收敛到一处；`util/__init__.py` 不 re-export，调用方按 `from xragent.util.heartbeat import ...` 直接用
（main.py 当前用法）。
```

改成

```
当前 7 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /
`heartbeat` / `http_parents`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；
v0.2.7 +heartbeat，见 ADR-0008；v0.2.8 +http_parents，见 ADR-0009）。
`heartbeat.py::start_heartbeat_thread(...)` 与 `http_parents.py::setup_http_parents_channel(...)`
分别把 main.py 中两段重复模板（heartbeat 7 行 while + try/except + wait；HTTP 父母通道 6+ 行 register + start + print）
收敛到 util/，调用方按 `from xragent.util.<module> import ...` 直接用；`util/__init__.py` 不 re-export（与 v0.1.1 起
保持一致，避免隐式副作用）。
```

设计意图：

- 把 `http_parents.py` 和 `heartbeat.py` 两个**main.py 起源**的 util/ 模块并列描述，因为它们抽的是 main.py 里
  两段不同的"重复模板"（一段是 watchdog heartbeat 线程；一段是 HTTP 父母通道启动段），口径一致。
- "util/__init__.py 不 re-export" 这条 ADR-0008 已立的约束在 ADR-0009 再次明示，因为 `http_parents.py` 也是
  `from xragent.util.http_parents import ...` 直接调用（main.py 当前用法），保持口径一致。

### D2. §二 模块清单 util/ 行加 `http_parents.py`

§二 模块清单的 util/ 行从

```
├── util/                      # 6 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers / heartbeat
│                             #   heartbeat.py: start_heartbeat_thread（v0.2.7，见 ADR-0008）
```

改成

```
├── util/                      # 7 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers / heartbeat / http_parents
│                             #   heartbeat.py:   start_heartbeat_thread（v0.2.7，见 ADR-0008）
│                             #   http_parents.py: setup_http_parents_channel（v0.2.8，见 ADR-0009）
```

设计意图：

- 把两个 main.py 起源的 util/ 模块并列对齐行首缩进，便于扫读时一眼定位 main.py 用了哪几个 util/ helper。
- 表格化 `start_heartbeat_thread` + `setup_http_parents_channel` 两个公开 API，未来 §三工具表如果引用 util/ 工具时有歧义
  可以反向 grep util/ 模块行。

### D3. §四不变量表格"高危工具须审批"行改措辞

§四 不变量表格 line 131 的实现位置列从

```
| 高危工具须审批 | `build_default_registry` 传 `evolution_enabled` 决定 evolution_tools 是否注册 |
```

改成

```
| 高危工具须审批 | `tools/registry.py::build_default_registry()` 无参调用；自动读 `Settings.evolution_enabled`，<br>`False` 时 unregister `propose_self_replace` + `terminate`（剩 15 个） |
```

设计意图：

- 明示"无参调用" — 防止未来有人按 ADR-0006 / ADR-0007 时代的"传参"理解去重构 `build_default_registry`，误改成"再次显式接参"。
- 用 `<br>` 而不是把单元格撑成两行（不变量表格视觉密度优先）；"剩 15 个" 与 §二模块清单 + §三工具表保持口径一致。
- 引用 `Settings.evolution_enabled` 而不是 `settings.evolution_enabled`，与 §一"配置 / settings" 行的实现位置写法对齐。

### D4. §五 版本对照加 v0.2.8 行

紧跟 v0.2.7 行后插入 v0.2.8：

```
| v0.2.8 | 架构 doc 同步：util/http_parents.py 抽取（6 → 7 模块）+ tools/registry.build_default_registry 不再接 evolution_enabled 参数（自动读 Settings.evolution_enabled）。util/http_parents.py 落地 commit 7bd65f9a；本 ADR-0009 doc sync | ADR-0009 |
```

设计意图：

- 一行说清两件 v0.2.8 的事（util/ +7 + registry 签名演进），commit 引用只列关键 commit（不重复列举 typing/refactor pass 的所有 commit）。
- 与 v0.2.7 行（同款格式："util/heartbeat.py 抽取 + memory schema 5.8 LRU + commit chain 追溯"）保持口径一致。

### D5. 顶部 ADR 链接列表加 ADR-0009

按 ADR-0008 顶部"ADR-0007 / ADR-0008"的格式追加：

```
[ADR-0008](...)（v0.2.7 重做：util/heartbeat.py + memory schema 5.8 LRU；前次 commit b78638d1 被 revert） /
[ADR-0009](adr/0009-architecture-v0-util-http-parents-and-registry-settings-coupling.md)（v0.2.8：util/http_parents.py 抽取 + build_default_registry 配置来源从传参改为读 Settings）。
```

设计意图：

- ADR 链接列表的顺序按 ADR 编号升序，与 §五版本对照行的 ADR 引用顺序一致；方便 git blame 时从 doc 顶部直接跳到对应 ADR。
- 简短注释里**明示**"build_default_registry 配置来源从传参改为读 Settings" — 这是 §四不变量 line 131 措辞变更的人话版
  summary，对那些只看 doc 顶部不展开 §四的读者最关键。

### D6. 新增约束（接 ADR-0008 D6 自检思路）

本轮 doc sync 必须额外做的 3 步自检 — **直接 grep src/ 验证**（不依赖 import，避免 pre-existing 缺模块问题）：

1. `ls src/xragent/util/*.py | grep -v __init__ | wc -l` 数**模块文件**（**不含** `__init__.py`），应得 7，与 doc §一"7 个模块" + §二 util/ 行注释匹配。
   （注意：裸 `ls src/xragent/util/*.py | wc -l` 会得 8 含 `__init__.py`，是 ADR-0008 D6-1 同样的小坑，本轮显式 `grep -v __init__` 修正。）
2. `grep -nE "^def build_default_registry\(" src/xragent/tools/registry.py` 拿函数签名，应是 `def build_default_registry() -> ToolRegistry:`（无参），
   与 doc §四 line 131 改后措辞"无参调用"匹配。
3. `grep -c '^    add("' src/xragent/tools/registry.py` 数工具注册调用数，应得 17（`evolution_enabled=false` 时 unregister 2 个，剩 15），
   与 doc §二 + §三"17 个 / 15 个" 口径匹配。用 grep 而非 `build_default_registry()` 动态调用是因为后者会 import 全工具链（当前 pre-existing 缺 `xragent.blacklist`，导致 `evolve_tools` import 失败 — 与本轮无关，但会让 D6 自检踩坑）。

如果自检失败（例如又有人新加了 util/ 模块但忘了同步），本 ADR 的 patch 自身也要 patch 进 fix — 不留 half-applied 状态。
**这是 ADR-0008 D6 的同款约束向 v0.2.8 的延伸**：D6 是"ADR-0009+ 的开 ADR 触发器"，本轮触发器响了一次（util/ 6 → 7），按 D6 写新 ADR 是预期行为。

## 五、影响

- **代码**：零改动，纯文档同步。
- **测试**：本轮改 doc 顺手跑 `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no` 确认 0 回归（实际影响 0；所有 pre-existing fail 仍 fail 但与本轮无关；预期 registry + util/ 增量都不引入新失败）。

## 六、参考

- ADR-0001：util/ 抽取口径（"出现 2+ 次且 ≥5 行"）。
- ADR-0006：v0.2.5 重做 precedent（落地 → revert → 重做三事件路径 + 自检约束 D7）。
- ADR-0008：v0.2.7 重做（util/heartbeat.py + memory schema 5.8 LRU；§四 D6 自检约束是本 ADR-0009 D6 的直接上游）。
- commit `7bd65f9a`：`autonomous: 重构抽公共函数 (round 615)` — util/http_parents.py 抽取（**保留**）。
- `src/xragent/tools/registry.py` 第 161 行：`def build_default_registry() -> ToolRegistry:`（无参）。
- `src/xragent/tools/registry.py` 第 273-275 行：`s = get_settings(); if not s.evolution_enabled: r.unregister(...)`。
- `src/xragent/core/react_loop.py` 第 179 行：`self.registry = registry or build_default_registry()`（无参调用，硬证据）。
- `src/xragent/config/settings.py` 第 59 行：`evolution_enabled: bool = True`（Settings 默认值）。
- `src/xragent/util/http_parents.py`：docstring 明确"不创建 input_queue"（调用方自管）+ "OSError 吞掉并 print"（端口 bind 失败不崩主进程）。
