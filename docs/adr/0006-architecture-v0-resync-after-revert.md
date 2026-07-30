# ADR-0006: architecture-v0.md 重新 sync（ADR-0005 落地被 revert 后，含 `--once` flag 修正）

> 状态：已采纳（v0.2.5）
> 时间：2026-07-30（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
> 上游 ADR：ADR-0005（前次 v0.2.5 sync，commit 4b390f19，被 commit b5a702fa revert）

## 一、背景

ADR-0005 在 commit 4b390f19 落地了 5 处失实的修正：

| # | 漂移点 |
| --- | --- |
| 1 | `watchdog/` 模块整体缺失 |
| 2 | tools/ 三个文件名错（`file_tools` / `web_tools` / `evolution_tools`） |
| 3 | `exec_tools.py` 漏列 + `run_cmd` 错挂 |
| 4 | `curl_url` / `web_search` 风险档位错（`low` → `medium`） |
| 5 | §四 缺"子进程异常可自愈"行 |

但该 commit **被 revert**（b5a702fa），doc 回到 ADR-0005 之前的状态，5 处失实全部复发。
revert 时未在 diary 留痕，无法确认动机；本轮重新触发 `TASK_TEMPLATES[6]` 时直接撞回同一组失实，
外加发现 **1 处新漂移**（见 D6），证明 ADR-0005 的盘点方向正确、只是落地被回滚，
本次按 ADR-0005 决策意图重新 sync，并补齐新增漂移。

## 二、为什么不直接 cherry-pick 4b390f19

不能直接 cherry-pick，原因：

1. **D6 新发现**：4b390f19 patch 在 §二 顶部 `main.py` 描述里把 CLI flags 写成
   "`--smoke / --serve / --autonomous / --as-supervised / --freeze`"，但
   `src/xragent/main.py::main()` 实际 argparse 还注册了 **`--once`**（单轮 ReAct），
   排在 `--serve` 之前。`--once` 是 `cmd_once(text, freeze)` 的入口，常用于人类
   父母"我想单步看 Agent 一轮思考"的场景，doc 不写它会让按 doc 操作的人找不到入口。
   这可能是 4b390f19 被 revert 的具体原因之一（"doc 与 main.py CLI 仍然对不上"）。
2. **`memory/manager.py.bak` 已不存在**：4b390f19 patch 在 §二 `memory/manager.py`
   行末写了 "`manager.py.bak 为历史备份，可清理`"，但本轮 `ls memory/` 时
   `manager.py.bak` 已经不在（推测在 4b390f19 落地到 revert 之间的某个 round
   顺手清理了）。本次 patch **不再提** 这个备份，避免描述指向不存在的文件。
3. **更小 patch、注释更清晰**：本轮从 ADR-0005 决策意图出发自己写一份 patch，
   而不是机械 re-apply；这样如果未来再有漂移，git blame 能精确指向本次决策。

## 三、决策

### D1（继承 ADR-0005 D1）. §一 五大核心"成长"行补 watchdog

```
成长 | evolve/metamorphosis.py + evolve/generations.py + autonomous.py（自驱动循环）
       + watchdog/supervisor.py（24h 自愈）+ watchdog/runtime_state.py（心跳文件）
```

### D2（继承 ADR-0005 D2）. §二 模块清单补 watchdog/ + 修 tools/ 文件名

- `autonomous.py` 行后插入：
  ```
  ├── watchdog/__init__.py
  ├── watchdog/runtime_state.py  # heartbeat 读写 + is_alive / restart_count / bump_restart
  ├── watchdog/supervisor.py     # 子进程守护：fork + heartbeat 检测 + restart + 世代记录
  ```
  （注：4b390f19 写"24h 子进程守护"，但 `heartbeat_interval_s=10` +
  `heartbeat_timeout_s=60` 意味着判定窗口是分钟级而非 24h；本轮去掉"24h"以贴合代码。）
- 修正 tools/ 区段：
  - `file_tools.py` → `fs_tools.py`（read_file / list_dir / write_file）
  - 新增 `exec_tools.py` 行（run_cmd）
  - `web_tools.py` → `web_search.py`（web_search + curl_url）
  - `evolution_tools.py` → `evolve_tools.py`（propose_self_replace / terminate）
- 在 tools/ 区段后追加一行文件名约定注释（沿用 4b390f19 引入的约定）。

### D3（继承 ADR-0005 D3）. §三 表头加风险档位说明 + curl_url / web_search 改 medium

§三 顶部加一行：
> 风险档位：`low`（只读/写受保护路径）·`medium`（外部 IO 但可观察/可中断）·`high`（不可逆写操作，需 HITL）。

表里 `web_search` / `curl_url` 风险列从 `low` 改 `medium`。

### D4（继承 ADR-0005 D4）. §四 关键不变量补"子进程异常可自愈"行

新增第 7 行（描述按代码收紧，呼应 D2 关于 24h 的修正）：
```
| 子进程异常可自愈 | watchdog/supervisor.py 定期读 runtime_state.json heartbeat，
                    超过 heartbeat_timeout_s 未更新则判僵死、SIGTERM 后 fork 新子进程
                    并 bump_restart；累计 restart_max_failures 次失败后停。
                    runtime_state.json 在 write_blacklist 里，Agent 不可改、自愈路径不被 Agent 干扰 |
```

### D5（继承 ADR-0005 D5）. §五 版本对照补 v0.2.5 一行 + 顶部 preamble 加 ADR-0006 链接

ADR-0005 的 v0.2.5 行本次直接补回（4b390f19 当时补过但被 revert）。

### D6（本轮新增）. §二 顶部 main.py CLI flag 列表补 `--once`

把 `main.py` 行注释里的 CLI flags 从
"`--smoke / --serve / --autonomous / --as-supervised / --freeze`"
改为实际 argparse 顺序
"`--smoke / --once / --serve / --as-supervised / --autonomous / --freeze`"，
并在用途列说明 `--once` 是"单轮 ReAct（含 HITL 审批）"。

### D7（新增约束）. 任何 doc 同步 patch 必须跑 argparse/CLI 字段一致性 sanity check

本轮发现的 `--once` 遗漏是因为 patch 作者只看了函数定义（`cmd_once` 在 file 里有定义）
但没看 argparse 注册行。下次写 doc 同步 patch 时，**必须**额外 grep 一遍
`parser.add_argument` 的 flag 列表与 doc 描述是否一致；同样适用于其它"CLI 工具入口"
文档（supervisor / metamorphosis）。

## 四、影响

- **代码**：零改动，纯文档同步。
- **测试**：本轮改 doc 顺手跑 `pytest -q --tb=no` 确认 0 回归（实际影响 0）。
- **风险消除**：同 ADR-0005 IV 节，外加消除"按 doc 跑 `python -m xragent.main --once` 找不到 flag"的入口失效。

## 五、与 ADR-0005 的差异（便于 git blame 追溯）

| 项 | ADR-0005 / commit 4b390f19 | ADR-0006 / 本次 |
| --- | --- | --- |
| watchdog 守护窗口 | 写"24h" | 写"超过 heartbeat_timeout_s"（按 settings.py 实际值） |
| `memory/manager.py.bak` 提示 | 在 §二 行末写"为历史备份，可清理" | 备份已删，不写 |
| main.py CLI flags | 漏 `--once` | 补齐 |
| 文件名约定注释 | 在 tools/ 区段后追加一行 | 保留 |
| 漂移事件数 | 5 处 | 5 处 + 1 处新增（--once） |

## 六、为什么单独留 ADR-0006 而非更新 ADR-0005

ADR-0005 的决策方向正确且已"已采纳"；本次失败是落地过程被 revert，而非
决策错误。更新 ADR-0005 会让 commit history 与"被 revert 一次"这件事脱钩，
不利于未来审计。单独 ADR-0006 + 引用 ADR-0005 让 git log 一眼看到
"v0.2.5 sync 经历了落地 → revert → 重做"三个事件。