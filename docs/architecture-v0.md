# XRAgent 架构摘要（v0.1 出生版）

> 完整方案在多次迭代中展开；此文档是 v0.1 出生时的快速地图。
> 当代码与本文档冲突时：**代码为准**，并在 `docs/adr/` 记录决策。详见 [ADR-0002](adr/0002-architecture-v0-sync.md) / [ADR-0003](adr/0003-snapshot-retention-v0.2.3.md) / [ADR-0004](adr/0004-tool-count-and-memory-recall.md) / [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)。

## 一、五大核心

| 核心 | 实现位置 |
| --- | --- |
| 梦想 | `AGENTS.md` + `core/dream.py` + `core/react_loop.py`（ReAct 主循环）+ `core/backend.py`（LLM 适配） |
| 父母 | `hitl/gate.py`（高危门）+ `http_server.py`（HIL 通道，HTTP `POST /message`） |
| 生活 | `tools/blacklist.py`（仓库根路径围栏 + 黑名单）+ `hitl/gate.py`（运行时审批） |
| 记忆 | `memory/manager.py`（`MemoryManager` 类，SQLite + 复合索引 (category,ts) / (category,priority,ts) 等，schema 详见 `manager.py` 建表 SQL；`write_blacklist` 保护 `memory/queue.jsonl` 不被 Agent 改） |
| 工具 | `tools/registry.py`（`build_default_registry()`）+ `tools/{fs,exec,web_search,git,memory,diary,evolve}_tools.py`（按职责拆分） |
| 自主 | `autonomous.py`（定时巡检 + `TASK_TEMPLATES`）+ `watchdog/supervisor.py`（24h 守护子 Agent + heartbeat 检测 + 子进程异常重启） |
| 成长 | `evolve/metamorphosis.py` + `evolve/generations.py` + `autonomous.py`（自驱动循环） |

补充说明：

- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。运行由 `watchdog/supervisor.py` 守护，详见 §四 子进程自愈不变量。
- **守护（watchdog）** 不单列核心，作为"自主 + 成长"的运行时支撑：`supervisor.py` fork 子 Agent
  跑 `main.py --autonomous`，定期读 `runtime_state.json` 的 `heartbeat_ts`；超过 `heartbeat_timeout_s`
  未更新则判僵死、SIGTERM 后 fork 新子进程并 `bump_restart()`；累计 `restart_max_failures` 次失败后停。
  `runtime_state.json` 在 `write_blacklist` 里，Agent 不可改、自愈路径不被 Agent 干扰。
- **util/** 是按"出现 2+ 次且 ≥5 行"原则抽出的共享小工具，避免过早抽象。
  当前 5 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers`
  （见 ADR-0001 D1，diary_archive + git_helpers 为 v0.1.1 后续增量）。
- **压缩策略**：`compression/hook.py` 是策略注册表，`compression/simple.py` 是默认实现；
  `react_loop.py` 在每轮 ReAct 已调用 `memory.compress_if_needed(...)`（详见 ADR-0002 D3）。

## 二、模块清单

```
src/xragent/
├── main.py                    # CLI 入口（--smoke / --serve / --autonomous / --as-supervised / --freeze）
├── config/settings.py         # pydantic-settings（v0.2.3 + snapshot_retention_days，见 ADR-0003 D3；
│                             #           + cmd_blacklist_patterns、push_interval_minutes，v0.2.3 后增量；
│                             #           + heartbeat_* / restart_max_failures / spawn_mode，watchdog 用）
├── core/dream.py              # AGENTS.md 加载
├── core/backend.py            # BackendProtocol + Mock + LangChain
├── core/turn.py               # TurnRecord + TraceRecorder
├── core/react_loop.py         # ReAct 主循环（含 compress_if_needed 调用）
├── memory/manager.py          # MemoryManager：SQLite 长期事实 + compress_if_needed 封装
│                             # （manager.py.bak 为历史备份，可清理）
├── compression/simple.py      # 最简压缩（SimpleCompression.compress）
├── compression/hook.py        # 压缩策略注册表（已注册 simple）
├── snapshot/side_git.py       # 每个 turn snapshot
│                             # v0.2.3 新增 cleanup_old_snapshots()，见 ADR-0003
├── watchdog/__init__.py
├── watchdog/runtime_state.py  # heartbeat 读写 + is_alive / restart_count / bump_restart
├── watchdog/supervisor.py     # 24h 子进程守护：fork + heartbeat 检测 + restart + 世代记录
├── evolve/metamorphosis.py    # 金蝉脱壳：编译新 main.py 并切换 entry
├── evolve/generations.py      # generations.jsonl 留痕
├── autonomous.py              # 定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl
├── hitl/gate.py               # HITL 门（高危动作 / 高危工具审批）
├── http_server.py             # HTTP 父通道（补全 HIL 通道，见 ADR-0001 D2）
├── tools/registry.py          # build_default_registry()：注册 15 个工具
│                             # （v0.2.3 后 +1：memory_recall，见 ADR-0004）
│                             # evolution_enabled=false 时剩 13 个（去 propose_self_replace + terminate）
├── tools/blacklist.py         # 路径围栏 + 黑名单校验
├── tools/memory_tools.py      # 4 个 memory_* 工具（save + 3 种 recall，见 ADR-0004）
├── tools/fs_tools.py          # read_file / list_dir / write_file
├── tools/exec_tools.py        # run_cmd
├── tools/web_search.py        # web_search + curl_url（带限流）
├── tools/diary_tools.py       # diary_write
├── tools/git_tools.py         # git_commit / git_push
├── tools/evolve_tools.py      # propose_self_replace / terminate（高危，HITL 门控）
├── util/                      # 5 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers
└── llm/                       # 占位包，目前仅 __init__.py
```

工具总数：**15 个**（`evolution_enabled=false` 时剩 13 个；`propose_self_replace` + `terminate`
属 evolve_tools，由 HITL 门控的 high-risk 工具）。

> 文件名约定：tools/ 按职责拆为 `fs_*`（文件）/ `exec_*`（执行）/ `web_search`（网络搜索）/
> `git_*` / `memory_*` / `diary_*` / `evolve_*`；本次 v0.2.5 重命名 4 个文件，详见 [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)。

## 三、注册工具（15）

来源：`src/xragent/tools/registry.py::build_default_registry()`

风险档位：`low`（只读/写受保护路径）·`medium`（外部 IO 但可观察/可中断）·`high`（不可逆写操作，需 HITL）。

| 工具 | 风险 | HITL | 用途 |
| --- | --- | --- | --- |
| `read_file`     | low    | 否 | 读仓库内文件 |
| `list_dir`      | low    | 否 | 列目录（不含 .git） |
| `web_search`    | medium | 否 | DuckDuckGo 搜索（top 5 URL） |
| `curl_url`      | medium | 否 | HTTP GET/POST（5min 限流 + diary 留痕） |
| `diary_write`   | low    | 否 | 写 diary/YYYY-MM-DD.md |
| `memory_save`   | low    | 否 | 存一条 fact 到长期记忆（`category: str` + `content: str`） |
| `memory_recall`        | low | 否 | 关键词 LIKE 召回 fact（"我说过什么关于 X 的事"），v0.2.3 后新增，见 ADR-0004 |
| `memory_recall_range`  | low | 否 | 按时间窗口召回 fact（"什么时候说的"） |
| `memory_top_frequent`  | low | 否 | 频次 top-N（"反复说过的点是什么"） |
| `write_file`    | high   | 是 | 写文件（路径围栏 + 黑名单校验） |
| `run_cmd`       | high   | 是 | shell（30s 超时 + binary 黑名单 + pattern 黑名单） |
| `git_commit`    | high   | 是 | git add+commit |
| `git_push`      | high   | 是 | git push 到 origin |
| `propose_self_replace` | high | 是 | 金蝉脱壳：commit → push → 编译 → supervisor 切换 |
| `terminate`     | high   | 是 | 优雅终止（supervisor 不再自动拉起） |

> §四 关键不变量里 14 → 15 与 §三 一致：3 个 recall 工具平级，补齐 `memory_recall` 后才是
> "3 种 recall 风格"（关键词 / 时间窗 / 频次），memory_tools.py 注释里也明说。
>
> 风险档位变更：v0.2.5 把 `web_search` / `curl_url` 从 `low` 升为 `medium`（外部 IO
> 但可观察：写 `diary/search-log.md` 留痕 + 5min 限流），与 registry 实际档位对齐，
> 避免未来若 HITL 扩展到 medium 档位时 doc 与契约错位，详见 ADR-0005 D3。

## 四、关键不变量

| 不变量 | 实现位置 |
| --- | --- |
| AGENTS.md / .env / runtime_state.json / .git/ 不可改 | `tools/blacklist.py` 路径黑名单（`write_blacklist`） |
| 危险 binary 不可用 | `config/settings.py::cmd_blacklist` + `cmd_blacklist_patterns`（v0.2.3 后增量） |
| HIL 通道是父母 | `hitl/gate.py`（仅响应人类父母指令）+ `http_server.py`（HTTP 父通道） |
| 高危工具须审批 | `build_default_registry` 传 `evolution_enabled` 决定 evolve_tools 是否注册 |
| Diary 是真相 | `diary/YYYY-MM-DD.md` 人类可读 + `diary/turns/*` 结构化日志（Agent 不可自我粉饰） |
| 失败可回滚 | `snapshot/side_git.py` 每 turn tag + v0.2.3 后 `cleanup_old_snapshots` 自动清理过期 tag（见 ADR-0003） |
| Push 节流 | `push_interval_minutes=30`（autonomous 模式每 30 min 批量 push 一次） |
| 子进程异常可自愈 | `watchdog/supervisor.py` 定期读 `runtime_state.json` `heartbeat_ts`，超过 `heartbeat_timeout_s` 未更新则 fork 新子进程并 `bump_restart()`；Agent 不可改 `runtime_state.json`（`write_blacklist` 保护），自愈路径不被 Agent 干扰 |

## 五、版本对照

| 版本 | 关键事件 | ADR |
| --- | --- | --- |
| v0.1.0 | 出生版（ReAct + HITL + 快照 + 记忆） | ADR-0001 |
| v0.1.1 | util/ 抽 diary_archive / git_helpers | ADR-0001 D1 |
| v0.1.2 | HTTP 父通道（补全 HIL） | ADR-0001 D2 |
| v0.2.0 | compression hook（simple） | ADR-0002 D3 |
| v0.2.3 | snapshot 保留策略 + cmd_blacklist_patterns | ADR-0003 |
| v0.2.4 | 工具清单 14 → 15（补 memory_recall） | ADR-0004 |
| v0.2.5 | doc 同步：补 watchdog/ 模块 + 修 tools/ 文件名 + 风险档位契约对齐 | ADR-0005（本文档） |
| v0.3 (planned) | 长期记忆强化（recall 工具 + 摘要压缩 hook 强化） | 待定 |
