# XRAgent 架构摘要（v0.1 出生版）

> 完整方案在多次迭代中展开；此文档是 v0.1 出生时的快速地图。
> 当代码与本文档冲突时：**代码为准**，并在 `docs/adr/` 记录决策。详见 [ADR-0002](adr/0002-architecture-v0-sync.md) / [ADR-0003](adr/0003-snapshot-retention-v0.2.3.md) / [ADR-0004](adr/0004-tool-count-and-memory-recall.md)。

## 一、五大核心

| 核心 | 实现位置 |
| --- | --- |
| 梦想 | `AGENTS.md` + `core/dream.py` + `core/react_loop.py`（ReAct 主循环）+ `core/backend.py`（LLM 适配） |
| 父母 | `hitl/gate.py` + `http_server.py` |
| 生活 | `tools/blacklist.py`（仓库根路径围栏 + 黑名单） |
| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003） |
| 成长 | `evolve/metamorphosis.py` + `evolve/generations.py` + `autonomous.py`（自驱动循环） |

补充说明：

- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。
- **util/** 是按"出现 2+ 次且 ≥5 行"原则抽出的共享小工具，避免过早抽象。
  当前 5 个模块：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers`
  （见 ADR-0001 D1，diary_archive + git_helpers 为 v0.1.1 后续增量）。
- **压缩策略**：`compression/hook.py` 是策略注册表，`compression/simple.py` 是默认实现；
  `react_loop.py` 在每轮 ReAct 已调用 `memory.compress_if_needed(...)`（详见 ADR-0002 D3）。

## 二、模块清单

```
src/xragent/
├── config/settings.py         # pydantic-settings（v0.2.3 + snapshot_retention_days，见 ADR-0003 D3；
│                             #           + cmd_blacklist_patterns、push_interval_minutes，v0.2.3 后增量）
├── core/dream.py              # AGENTS.md 加载
├── core/backend.py            # BackendProtocol + Mock + LangChain
├── core/turn.py               # TurnRecord + TraceRecorder
├── core/react_loop.py         # ReAct 主循环（含 compress_if_needed 调用）
├── memory/manager.py          # SQLite 长期事实 + compress_if_needed 封装
├── compression/simple.py      # 最简压缩（SimpleCompression.compress）
├── compression/hook.py        # 压缩策略注册表（已注册 simple）
├── snapshot/side_git.py       # 每个 turn snapshot
│                             # v0.2.3 新增 cleanup_old_snapshots()，见 ADR-0003
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
├── tools/file_tools.py        # read_file / list_dir / write_file / run_cmd
├── tools/web_tools.py         # web_search / curl_url（带限流）
├── tools/diary_tools.py       # diary_write
├── tools/git_tools.py         # git_commit / git_push
├── tools/evolution_tools.py   # propose_self_replace / terminate（高危，HITL 门控）
├── util/                      # 5 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers
└── llm/                       # 占位包，目前仅 __init__.py
```

工具总数：**15 个**（`evolution_enabled=false` 时剩 13 个；`propose_self_replace` + `terminate`
属 evolution_tools，由 HITL 门控的 high-risk 工具）。

## 三、注册工具（15）

来源：`src/xragent/tools/registry.py::build_default_registry()`

| 工具 | 风险 | HITL | 用途 |
| --- | --- | --- | --- |
| `read_file`     | low | 否 | 读仓库内文件 |
| `list_dir`      | low | 否 | 列目录（不含 .git） |
| `web_search`    | low | 否 | DuckDuckGo 搜索（top 5 URL） |
| `curl_url`      | low | 否 | HTTP GET/POST（5min 限流 + diary 留痕） |
| `diary_write`   | low | 否 | 写 diary/YYYY-MM-DD.md |
| `memory_save`   | low | 否 | 存一条 fact 到长期记忆 |
| `memory_recall`        | low | 否 | 关键词 LIKE 召回 fact（"我说过什么关于 X 的事"），v0.2.3 后新增，见 ADR-0004 |
| `memory_recall_range`  | low | 否 | 按时间窗口召回 fact（"什么时候说的"） |
| `memory_top_frequent`  | low | 否 | 频次 top-N（"反复说过的点是什么"） |
| `write_file`    | high | 是 | 写文件（路径围栏 + 黑名单校验） |
| `run_cmd`       | high | 是 | shell（30s 超时 + binary 黑名单 + pattern 黑名单） |
| `git_commit`    | high | 是 | git add+commit |
| `git_push`      | high | 是 | git push 到 origin |
| `propose_self_replace` | high | 是 | 金蝉脱壳：commit → push → 编译 → supervisor 切换 |
| `terminate`     | high | 是 | 优雅终止（supervisor 不再自动拉起） |

> §四 关键不变量里 14 → 15 与 §三 一致：3 个 recall 工具平级，补齐 `memory_recall` 后才是
> "3 种 recall 风格"（关键词 / 时间窗 / 频次），memory_tools.py 注释里也明说。

## 四、关键不变量

| 不变量 | 实现位置 |
| --- | --- |
| AGENTS.md / .env / runtime_state.json / .git/ 不可改 | `tools/blacklist.py` 路径黑名单（`write_blacklist`） |
| 危险 binary 不可用 | `config/settings.py::cmd_blacklist` + `cmd_blacklist_patterns`（v0.2.3 后增量） |
| HIL 通道是父母 | `hitl/gate.py`（仅响应人类父母指令） |
| 高危工具须审批 | `build_default_registry` 传 `evolution_enabled` 决定 evolution_tools 是否注册 |
| Diary 是真相 | `diary/YYYY-MM-DD.md` 人类可读 + `diary/turns/*` 结构化日志（Agent 不可自我粉饰） |
| 失败可回滚 | `snapshot/side_git.py` 每 turn tag + v0.2.3 后 `cleanup_old_snapshots` 自动清理过期 tag（见 ADR-0003） |
| Push 节流 | `push_interval_minutes=30`（autonomous 模式每 30 min 批量 push 一次） |

## 五、版本对照

| 版本 | 关键事件 | ADR |
| --- | --- | --- |
| v0.1.0 | 出生版（ReAct + HITL + 快照 + 记忆） | ADR-0001 |
| v0.1.1 | util/ 抽 diary_archive / git_helpers | ADR-0001 D1 |
| v0.1.2 | HTTP 父通道（补全 HIL） | ADR-0001 D2 |
| v0.2.0 | compression hook（simple） | ADR-0002 D3 |
| v0.2.3 | snapshot 保留策略 + cmd_blacklist_patterns | ADR-0003 |
| v0.2.4 | 工具清单 14 → 15（补 memory_recall） | ADR-0004（本文档） |
| v0.3 (planned) | 长期记忆强化（recall 工具 + 摘要压缩 hook 强化） | 待定 |
