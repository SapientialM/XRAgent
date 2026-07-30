# XRAgent 架构摘要（v0.1 出生版）

> 完整方案在多次迭代中展开；此文档是 v0.1 出生时的快速地图。
> 当代码与本文档冲突时：**代码为准**，并在 `docs/adr/` 记录决策。
> 详见 [ADR-0002](adr/0002-architecture-v0-sync.md) / [ADR-0003](adr/0003-snapshot-retention-v0.2.3.md) /
> [ADR-0004](adr/0004-tool-count-and-memory-recall.md) /
> [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)（v0.2.5 首次 sync，commit 4b390f19 被 revert） /
> [ADR-0006](adr/0006-architecture-v0-resync-after-revert.md)（v0.2.5 重做） /
> [ADR-0007](adr/0007-architecture-v0-tool-count-read-file-original-size.md)（v0.3 工具面 + read_file.original_size sync） /
> [ADR-0008](adr/0008-util-heartbeat-extraction.md)（v0.2.7 util/heartbeat.py 抽取，util/ 5→6） /
> [ADR-0009](adr/0009-memory-5.8-lru-tracking.md)（v0.2.7 memory Fact.last_accessed_ts + touch_fact + recall_lru）。

## 一、五大核心

| 核心 | 实现位置 |
| --- | --- |
| 梦想 | `AGENTS.md` + `core/dream.py` + `core/react_loop.py`（ReAct 主循环）+ `core/backend.py`（LLM 适配） |
| 父母 | `hitl/gate.py` + `http_server.py` |
| 生活 | `tools/blacklist.py`（仓库根路径围栏 + 黑名单） |
| 记忆 | `memory/manager.py`（v0.2.7 含 LRU 追踪：`Fact.last_accessed_ts` + `touch_fact` + `recall_lru`，见 ADR-0009）+ `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003） |
| 成长 | `evolve/metamorphosis.py` + `evolve/generations.py` + `autonomous.py`（自驱动循环）<br>+ `watchdog/supervisor.py`（子进程异常自愈）+ `watchdog/runtime_state.py`（心跳文件，见 ADR-0005/0006） |

补充说明：

- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。
- **Watchdog / Supervisor**（见 ADR-0005 / ADR-0006）：与 autonomous 是两条线——
  autonomous 主动按 TASK_TEMPLATES 推进任务，watchdog 被动守护子进程存活（heartbeat 超时则 SIGTERM + fork）。
  守护窗口由 `settings.heartbeat_timeout_s` 控制（当前 60s），并非"24h"那种长周期。
  `runtime_state.json` 路径在 `tools/blacklist.py` 黑名单里，Agent 不可改、自愈路径不被 Agent 干扰。
- **util/** 是按"出现 2+ 次且 ≥5 行"原则抽出的共享小工具，避免过早抽象。
  当前 6 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` /
  `git_helpers` / `heartbeat`（v0.2.7 从 main.py 抽重复心跳线程模式，见 ADR-0008；
  `diary_archive` + `git_helpers` 为 v0.1.1 后续增量）。
- **压缩策略**：`compression/hook.py` 是策略注册表，`compression/simple.py` 是默认实现；
  `react_loop.py` 在每轮 ReAct 已调用 `memory.compress_if_needed(...)`（详见 ADR-0002 D3）。

## 二、模块清单

```
src/xragent/
├── main.py                    # CLI 入口（--smoke / --once / --serve / --as-supervised
│                             #           / --autonomous / --freeze，见 ADR-0006 D6）
├── config/settings.py         # pydantic-settings（v0.2.3 + snapshot_retention_days，见 ADR-0003 D3；
│                             #           + cmd_blacklist_patterns、push_interval_minutes，v0.2.3 后增量；
│                             #           + heartbeat_interval_s / heartbeat_timeout_s / restart_max_failures，
│                             #           watchdog 用，见 ADR-0006）
├── core/dream.py              # AGENTS.md 加载
├── core/backend.py            # BackendProtocol + Mock + LangChain
├── core/turn.py               # TurnRecord + TraceRecorder
├── core/react_loop.py         # ReAct 主循环（含 compress_if_needed 调用）
├── memory/manager.py          # MemoryManager：SQLite 长期事实 + compress_if_needed 封装
│                             # v0.2.7 加 Fact.last_accessed_ts / idx_facts_last_accessed_ts /
│                             # touch_fact / recall_lru（LRU 追踪，见 ADR-0009）
├── compression/simple.py      # 最简压缩（SimpleCompression.compress，deque(maxlen) O(1) 头插）
├── compression/hook.py        # 压缩策略注册表（已注册 simple）
├── snapshot/side_git.py       # 每个 turn snapshot
│                             # v0.2.3 新增 cleanup_old_snapshots()，见 ADR-0003
├── watchdog/__init__.py
├── watchdog/runtime_state.py  # heartbeat 读写 + is_alive / restart_count / bump_restart
├── watchdog/supervisor.py     # 子进程守护：fork + heartbeat 检测 + restart + 世代记录
├── evolve/metamorphosis.py    # 金蝉脱壳：编译新 main.py 并切换 entry
├── evolve/generations.py      # generations.jsonl 留痕
├── autonomous.py              # 定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl
├── hitl/gate.py               # HITL 门（高危动作 / 高危工具审批）
├── http_server.py             # HTTP 父通道（补全 HIL 通道，见 ADR-0001 D2）
├── tools/registry.py          # build_default_registry()：注册 17 个工具
│                             # （v0.2.3 后 +1：memory_recall，见 ADR-0004；
│                             #  v0.3 后 +1：memory_recall_by_tag，见 ADR-0007）
│                             # evolution_enabled=false 时剩 15 个（去 propose_self_replace + terminate）
├── tools/blacklist.py         # 路径围栏 + 黑名单校验（含 runtime_state.json 路径）
├── tools/memory_tools.py      # 5 个 memory_* 工具（save + 4 种 recall，见 ADR-0004 / ADR-0007）
├── tools/fs_tools.py          # read_file / list_dir / write_file
│                             # read_file v0.3+ 多返回 original_size（截断时与 size 不同），见 ADR-0007
├── tools/exec_tools.py        # run_cmd（独立模块，避免与 fs_tools 的纯文件操作混淆）
├── tools/web_search.py        # web_search + curl_url（带限流）
├── tools/diary_tools.py       # diary_write
├── tools/git_tools.py         # git_commit / git_push / snapshot_cleanup（medium，见 ADR-0007）
├── tools/evolve_tools.py      # propose_self_replace / terminate（高危，HITL 门控）
├── util/                      # 6 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers / heartbeat
└── llm/                       # 占位包，目前仅 __init__.py
```

> 文件名约定（见 ADR-0005 / ADR-0006）：tools/ 按职责拆为 `fs_*`（文件）/ `exec_*`（执行）/
> `web_search`（网络搜索）/ `git_*` / `memory_*` / `diary_*` / `evolve_*`；
> v0.2.5 重命名 4 个文件 + 新增 `exec_tools.py`，详见 [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)。

工具总数：**17 个**（`evolution_enabled=false` 时剩 15 个；`propose_self_replace` + `terminate`
属 evolve_tools，由 HITL 门控的 high-risk 工具）。

## 三、注册工具（17）

来源：`src/xragent/tools/registry.py::build_default_registry()`

风险档位：`low`（只读/写受保护路径）·`medium`（外部 IO 但可观察/可中断）·`high`（不可逆写操作，需 HITL）。

| 工具 | 风险 | HITL | 用途 |
| --- | --- | --- | --- |
| `read_file`     | low | 否 | 读仓库内文件 |
| `list_dir`      | low | 否 | 列目录（不含 .git） |
| `web_search`    | medium | 否 | DuckDuckGo 搜索（top 5 URL，外部 IO） |
| `curl_url`      | medium | 否 | HTTP GET/POST（5min 限流 + diary 留痕，外部 IO） |
| `diary_write`   | low | 否 | 写 diary/YYYY-MM-DD.md |
| `memory_save`   | low | 否 | 存一条 fact 到长期记忆 |
| `memory_recall`        | low | 否 | 关键词 LIKE 召回 fact（"我说过什么关于 X 的事"），v0.2.3 后新增，见 ADR-0004 |
| `memory_recall_range`  | low | 否 | 按时间窗口召回 fact（"什么时候说的"） |
| `memory_top_frequent`  | low | 否 | 频次 top-N（"反复说过的点是什么"） |
| `memory_recall_by_tag` | low | 否 | 按 tag 交集召回 fact（"标记过 X 的事"），v0.3 后新增，见 ADR-0007 |
| `snapshot_cleanup`     | medium | 否 | 删除过期 snapshot（snapshot/side_git.cleanup_old_snapshots 暴露），v0.2.3+；见 ADR-0007 |
| `write_file`    | high | 是 | 写文件（路径围栏 + 黑名单校验） |
| `run_cmd`       | high | 是 | shell（30s 超时 + binary 黑名单 + pattern 黑名单） |
| `git_commit`    | high | 是 | git add+commit |
| `git_push`      | high | 是 | git push 到 origin |
| `propose_self_replace` | high | 是 | 金蝉脱壳：commit → push → 编译 → supervisor 切换 |
| `terminate`     | high | 是 | 优雅终止（supervisor 不再自动拉起） |

> §四 关键不变量里 15 → 17 与 §三 一致：4 个 recall 工具平级，补齐 `memory_recall_by_tag` 后才是
> "4 种 recall 风格"（关键词 / 时间窗 / 频次 / 标签），memory_tools.py 注释里也明说。

## 四、关键不变量

| 不变量 | 实现位置 |
| --- | --- |
| AGENTS.md / .env / runtime_state.json / .git/ 不可改 | `tools/blacklist.py` 路径黑名单（`write_blacklist`） |
| 危险 binary 不可用 | `config/settings.py::cmd_blacklist` + `cmd_blacklist_patterns`（v0.2.3 后增量） |
| HIL 通道是父母 | `hitl/gate.py`（仅响应人类父母指令） |
| 高危工具须审批 | `build_default_registry` 传 `evolution_enabled` 决定 evolution_tools 是否注册 |
| Diary 是真相 | `diary/YYYY-MM-DD.md` 人类可读 + `diary/turns/*` 结构化日志（Agent 不可自我粉饰） |
| 失败可回滚 | `snapshot/side_git.py` 每 turn tag + v0.2.3 后 `cleanup_old_snapshots` 自动清理过期 tag（见 ADR-0003）；HUMAN 暴露成 `snapshot_cleanup` 工具供父母手动触发（见 ADR-0007） |
| Push 节流 | `push_interval_minutes=30`（autonomous 模式每 30 min 批量 push 一次） |
| 子进程异常可自愈 | `watchdog/supervisor.py` 定期读 `runtime_state.json` heartbeat，超过 `heartbeat_timeout_s` 未更新则判僵死、SIGTERM 后 fork 新子进程并 `bump_restart()`；累计 `restart_max_failures` 次失败后停。`runtime_state.json` 在 `write_blacklist` 里，Agent 不可改、自愈路径不被 Agent 干扰（见 ADR-0005 / ADR-0006） |
| read_file 契约演进 | `tools/fs_tools.py::read_file` v0.3+ 多返回 `original_size` 字段（截断场景下与 `size` 不同，让父母看到真实大小），见 ADR-0007 |
| 心跳线程抽象 | v0.2.7 起 `main.py` 两处重复心跳线程统一调 `util/heartbeat.start_heartbeat_thread(stop_predicate, interval_s, name)`，避免再抄出第三份变体；daemon=True（见 ADR-0008） |
| 记忆 LRU 可观测 | v0.2.7 起 `MemoryManager` 暴露 `recall_lru(k)` 与 `touch_fact(fact_id)`，配合 `Fact.last_accessed_ts` 索引 `idx_facts_last_accessed_ts`，让冷数据回收 / 召回统计可量化（见 ADR-0009） |

## 五、版本对照

| 版本 | 关键事件 | ADR |
| --- | --- | --- |
| v0.1.0 | 出生版（ReAct + HITL + 快照 + 记忆） | ADR-0001 |
| v0.1.1 | util/ 抽 diary_archive / git_helpers | ADR-0001 D1 |
| v0.1.2 | HTTP 父通道（补全 HIL） | ADR-0001 D2 |
| v0.2.0 | compression hook（simple） | ADR-0002 D3 |
| v0.2.3 | snapshot 保留策略 + cmd_blacklist_patterns | ADR-0003 |
| v0.2.4 | 工具清单 14 → 15（补 memory_recall） | ADR-0004 |
| v0.2.5 | 架构 doc 同步：watchdog/ 入表 + tools/ 重命名 4 文件 + 风险档位 medium + 自愈不变量（首次 ADR-0005 commit 4b390f19 被 revert，本轮 ADR-0006 重做） | ADR-0005 / ADR-0006（本文档） |
| v0.2.6 | 架构 doc 同步：工具面 15 → 17（+snapshot_cleanup +memory_recall_by_tag）+ read_file.original_size + memory_tools 注释 4→5 | ADR-0007 |
| v0.2.7 | util/heartbeat.py 抽取（util/ 5→6）+ memory 5.8 LRU 追踪（Fact.last_accessed_ts + touch_fact + recall_lru） | ADR-0008 / ADR-0009（本文档） |
| v0.3 (planned) | 长期记忆强化（recall 工具全量上线 ✅；待办：摘要压缩 hook 强化） | 待定 |