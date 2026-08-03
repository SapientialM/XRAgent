# XRAgent 架构摘要（v0.1 出生版）

> 完整方案在多次迭代中展开；此文档是 v0.1 出生时的快速地图。
> 当代码与本文档冲突时：**代码为准**，并在 `docs/adr/` 记录决策。
> 详见 [ADR-0002](adr/0002-architecture-v0-sync.md) / [ADR-0003](adr/0003-snapshot-retention-v0.2.3.md) /
> [ADR-0004](adr/0004-tool-count-and-memory-recall.md) /
> [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)（v0.2.5 首次 sync，commit 4b390f19 被 revert） /
> [ADR-0006](adr/0006-architecture-v0-resync-after-revert.md)（v0.2.5 重做） /
> [ADR-0007](adr/0007-architecture-v0-tool-count-read-file-original-size.md)（v0.3 工具面 + read_file.original_size sync） /
> [ADR-0008](adr/0008-architecture-v0-util-heartbeat-and-memory-5-8-lru.md)（v0.2.7 重做：util/heartbeat.py + memory schema 5.8 LRU；前次 commit b78638d1 被 revert） /
> [ADR-0009](adr/0009-architecture-v0-util-http-parents-and-registry-settings-coupling.md)（v0.2.8：util/http_parents.py 抽取 + build_default_registry 配置来源从传参改为读 Settings）。
> [ADR-0010](adr/0010-architecture-v0-autonomous-iter-tasks-and-hitl-gate-pure-functions.md)（v0.2.9：autonomous.iter_tasks 生成器 + hitl/gate._parse_stdin_line 纯函数化）。
> [ADR-0011](adr/0011-architecture-v0-registry-internals-tracked-files-and-autonomous-window-s.md)（v0.2.10 + v0.2.11 重做：registry 内部结构展开 + manager.py.bak / __tools_probe__.txt 留痕 + autonomous.next_task window_s + hook.py import 整理；前次 commit 4f970a4d 被 revert）。
> [ADR-0012](adr/0012-architecture-v0-doc-sync-tool-count-and-scoring.md)（v0.3.1：工具面 17 → 19 + §三表补 2 行 + §四剩 17 + §二 memory_tools 7 个 + §三表底 5 种 recall + §二模块清单 scoring/ 占位登记；commit `032d78f5`）。
> [ADR-0013](adr/0013-architecture-v0-v0.3.1-doc-landing-and-manager-py-bak-removal.md)（v0.3.1 doc sync 落地：应用 ADR-0012 所有 D1-D7 + manager.py.bak 删除回溯 D8）。
> [ADR-0014](adr/0014-architecture-v0-schema-5.9-and-stale-line-counts.md)（v0.5：schema 5.9 整理 doc sync 设计——§一 5.8→5.9 + §二行数 305→317 + §五 v0.5 行 + 顶部 ADR 清单）。
> [ADR-0015](adr/0015-architecture-v0-landing-adr-0014-d1-d4.md)（v0.5：实际落地 ADR-0014 D1-D4——commit `f3d60758` 只新增了 ADR 文件，architecture-v0.md 的 4 处 drift（D1/D2/D4/D5）实际由本 ADR-0015 commit 修复；D3 §二 memory/manager.py 行注释一并按 D1 精神同步）。
> [ADR-0016](adr/0016-architecture-v0-v0.5.x-snapshot-tag-index-and-count-cleanup.md)（v0.5.6~v0.5.9 + v0.11：snapshot/_tag_index.py 共享原语 + snapshot/count_cleanup.py 数量兜底 + dry_run）。
> [ADR-0017](adr/0017-architecture-v0-doc-vs-code-drift-scan.md)（v0.13.1 doc sync：scoring/ 占位包状态从 v0.3.1 到 v0.13.1 持续缺 __init__.py、未 git tracked，重新确认这件事并同步 §二 / §四 / §五；commit `3c1e2ae`）。
> [ADR-0018](adr/0018-architecture-v0-util-print-guard-and-scoring-empty.md)（v0.10 round 215+ close-out doc sync：util/print_guard.py 抽取补录（§一 §二 §五）+ scoring/ 二次清空措辞更新（§二 §四）；commit `59387b4d`）。
> [ADR-0019](adr/0019-architecture-v0-snapshot-age-cleanup-standalone.md)（v0.11+ round 231 doc sync：snapshot/age_cleanup.py 时间清理 standalone 镜像抽取（§一 §二 §四 §五），commit `fbe16191`；side_git.py inline wrapper 是否改 caller→callee 留给后续 round）。
> [ADR-0020](adr/0020-architecture-v0-round-235-adr-0018-d1-d2-doc-landing.md)（round 235 close-out：ADR-0018 D1/D2 doc 修复实际落地 + ADR-0019 D1-D5 全部已落地确认 —— 仅 doc 同步，未碰 src/）。
> [ADR-0021](adr/0021-architecture-v0-round-325-adr-0020-redo-and-scoring-truly-gone.md)（round 325+ close-out：ADR-0020 round 235 落地的 4 处 doc 修复全部反弹重做 + scoring/ 目录真正消失 —— 仅 doc 同步，未碰 src/）。
> [ADR-0022](adr/0022-architecture-v0-round-405-doc-vs-code-drift-scan.md)（round 405 drift 扫描：10 处 code-vs-doc 失真修复方案 + ADR-0018/0020/0021 错误前提更正 —— 仅 doc 同步，未碰 src/）。
> [ADR-0023](adr/0023-architecture-v0-round-562-drift-scan-and-adr-0022-landing.md)（round 562 drift 扫描：ADR-0022 实际落地确认 + 5.10/5.11 schema + v0.4 scoring baseline + snapshot/inspect + v0.10 print_guard 二次入表 —— 仅 doc 同步，未碰 src/）。
> [ADR-0024](adr/0024-architecture-v0-round-582-actual-doc-landing.md)（v0.13.2 round 582 doc sync：autonomous journal（diary 头部预览 + round_done 留痕）+ autonomous rng 显式参数化（可选）+ tools/web_search.py 5min 限流改造（per-host throttle）；§一 / §三 / §四 / §五 全部 doc 同步落地）。

## 一、五大核心

| 核心 | 实现位置 |
| --- | --- |
| 梦想 | `AGENTS.md` + `core/dream.py` + `core/react_loop.py`（ReAct 主循环）+ `core/backend.py`（LLM 适配） |
| 父母 | `hitl/gate.py` + `http_server.py` |
| 生活 | `tools/blacklist.py`（仓库根路径围栏 + 黑名单） |
| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>+ `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）<br>+ `snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，与 `count_cleanup.py` 对称，见 ADR-0019）<br>`memory/manager.py` 当前有效 schema **5.9**（5.0 基线 + 5.1 `source_turn_idx` + 5.3 `priority` + 5.4 `idx_facts_tags`（v0.5 5.9 二次回填）+ 5.5 `archived` + 5.6 `title` + 5.7 `confidence` + 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建），基线见 ADR-0004，5.8 LRU 增量见 ADR-0008，5.9 索引回填见 ADR-0014<br>注：常量 `SCHEMA_VERSION = 58` 未 bump 是已知遗留（5.9 migration 是 DDL-only 的二次回填，不改字段），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准 |
| 成长 | `evolve/metamorphosis.py` + `evolve/generations.py` + `autonomous.py`（自驱动循环）<br>+ `watchdog/supervisor.py`（子进程异常自愈）+ `watchdog/runtime_state.py`（心跳文件，见 ADR-0005/0006） |

补充说明：

- **自驱动（autonomous）** 不是 AGI，是"按 task templates + ReAct + commit"在没人在时也稳定推进的循环；
  模板见 `src/xragent/autonomous.py::TASK_TEMPLATES`（共 8 个），默认冷却 2h（`DEFAULT_COOLDOWN_S=7200`），
  `memory/queue.jsonl` 留痕（不入 git）。
  公开 API：`next_task(rng=None, journal=None, window_s=DEFAULT_COOLDOWN_S)` 选一个不在 cooldown 里的任务；`window_s` 可调（v0.2.11，见 ADR-0011 D4），便于测试时短时间绕过冷却、不污染 module 常量；`record_done(task, turn_id, summary)` append-only 留痕；
│                             #   journal 写盘（v0.13.2，见 ADR-0024）：next_task 选 task 后 journal 日志写一行 entry 到 memory/queue.jsonl，
│                             #   record_done 后写 round_done 收尾；可选用于断点复盘 / 外部观测。
│                             #   rng 参数显式化（v0.13.2，见 ADR-0024）：next_task(rng=None, journal=None, window_s=DEFAULT_COOLDOWN_S)
│                             #   —— rng 是测试注入口（注入 Random(seed) 可复现顺序），journal 是 None 即不写盘。
  **`iter_tasks(stop_check)`** 是生成器（v0.2.9，见 ADR-0010），每次 `next()` 拉一次 `next_task()`，直到 `stop_check()` 返回
  True 才停 —— 落地测试用，main.py 主循环当前仍走 imperative `next_task` 路径（待后续切换）；
  3 个 module-level helper：`task_queue_path()` / `task_cooldown_key(task)` / `_recent_titles(window_s)` 全部带
  Google-style docstring 与 PEP 604 类型注解（v0.2.9 公开化）。
- **父母（HITL 门）** 内部结构（v0.2.9，见 ADR-0010）：stdin 解析抽到模块级纯函数 `_parse_stdin_line(line)`，
  只依赖模块常量 `_APPROVE_INPUTS` / `_REJECT_INPUTS` / `_EDIT_PREFIX`，不读 stdin、不写 stderr；
  决策策略用 `_DEFAULT_POLICIES: dict[str, Decision]` 收敛 2 个硬编码 if 分支。
  目的：让 stdin 解析 + 决策分支**可单测**，无需 mock stdin 或 fork 子进程。
- **Watchdog / Supervisor**（见 ADR-0005 / ADR-0006）：与 autonomous 是两条线——
  autonomous 主动按 TASK_TEMPLATES 推进任务，watchdog 被动守护子进程存活（heartbeat 超时则 SIGTERM + fork）。
  守护窗口由 `settings.heartbeat_timeout_s` 控制（当前 60s），并非"24h"那种长周期。
  `runtime_state.json` 路径在 `tools/blacklist.py` 黑名单里，Agent 不可改、自愈路径不被 Agent 干扰。
- **util/** 是按"出现 2+ 次且 ≥5 行"原则抽出的共享小工具，避免过早抽象。
  当前 **8 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` /
  `heartbeat` / `http_parents` / `web_search_rl`（见 ADR-0001 D1；v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；
  v0.2.8 +http_parents，见 ADR-0009；v0.13.2 +web_search_rl，见 ADR-0024）。
  `heartbeat.py::start_heartbeat_thread(...)` 与 `http_parents.py::setup_http_parents_channel(...)` 分别把
  main.py 中两段重复模板（heartbeat 7 行 while + try/except + wait；HTTP 父母通道 6+ 行 register + start + print）
  收敛到 util/，调用方按 `from xragent.util.<module> import ...` 直接用；`util/__init__.py` 不 re-export
  （与 v0.1.1 起保持一致，避免隐式副作用）。
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
│                             # 当前有效 schema 5.9（v0.2.7 +LRU 5.8；v0.5 5.9 二次回填 5.4/5.6 丢失的
│                             # idx_facts_tags / idx_facts_title + 配套 recent() method），见 ADR-0004 / ADR-0008 / ADR-0014
├── compression/simple.py      # 最简压缩（SimpleCompression.compress）
├── compression/hook.py        # 压缩策略注册表（已注册 simple）；v0.2.10 import 整理
│                             # （顶部 import + 无 noqa；见 ADR-0011 D5）
├── snapshot/side_git.py       # 每个 turn snapshot
│                             # v0.2.3 新增 cleanup_old_snapshots()，见 ADR-0003
├── snapshot/_tag_index.py     # v0.5.x 抽出: list_xragent_turn_tags / parse_xragent_turn_tags
│                             #          / delete_tags 三个共享原语，让 cleanup 路径只剩策略
│                             #          (time-cutoff / count-slice)，不再重复 for-each-ref + 行解析
├── snapshot/count_cleanup.py  # v0.11: cleanup_old_snapshots_by_count(max_count, dry_run=False)
│                             #          按 creatordate 数量兜底，与 cleanup_old_snapshots 互不冲突
├── snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)
│                             #          时间清理 standalone 镜像（与 count_cleanup 对称），走 _tag_index helper
│                             #          commit `fbe16191`，见 ADR-0019；side_git.py 旧 inline wrapper 保留
├── watchdog/__init__.py
├── watchdog/runtime_state.py  # heartbeat 读写 + is_alive / restart_count / bump_restart
├── watchdog/supervisor.py     # 子进程守护：fork + heartbeat 检测 + restart + 世代记录
├── evolve/metamorphosis.py    # 金蝉脱壳：编译新 main.py 并切换 entry
├── evolve/generations.py      # generations.jsonl 留痕
├── autonomous.py              # 定时巡检 + TASK_TEMPLATES（8 个）+ queue.jsonl
│                             # 公开 API：next_task(rng=None, journal=None, window_s=DEFAULT_COOLDOWN_S)
│                             #          / record_done / iter_tasks（v0.2.9 生成器，见 ADR-0010）
│                             #          + task_queue_path / task_cooldown_key / _recent_titles（v0.2.9 公开化）；
│                             #   next_task 加 window_s 参数（v0.2.11，见 ADR-0011 D4），便于测试时短时间绕过冷却
│                             #   journal 写盘（v0.13.2，见 ADR-0024）：next_task 选 task 后 journal 日志写一行 entry 到 memory/queue.jsonl，
│                             #   record_done 后写 round_done 收尾；可选用于断点复盘 / 外部观测。
│                             #   rng 参数显式化（v0.13.2，见 ADR-0024）：next_task(rng=None, journal=None, window_s=DEFAULT_COOLDOWN_S)
│                             #   —— rng 是测试注入口（注入 Random(seed) 可复现顺序），journal 是 None 即不写盘。
├── hitl/gate.py               # HITL 门（高危动作 / 高危工具审批）
│                             # 内部：_parse_stdin_line 纯函数 + _DEFAULT_POLICIES dict（v0.2.9，见 ADR-0010）
├── http_server.py             # HTTP 父通道（补全 HIL 通道，见 ADR-0001 D2）
├── tools/registry.py          # build_default_registry() + 完整 ToolRegistry 注册中心
│                             # （v0.2.10 抽出 _safe_call helper，317 行，结构展开）：
│                             #   - ToolDef dataclass（name/description/input_schema/risk/handler）
│                             #   - ToolRegistry class 六方法：register / unregister / get / names / specs / run
│                             #   - 5 module-level helper：
│                             #       _HitlRejected sentinel（避免 rejection 走 handler 异常分支）
│                             #       _HitlOutcome NamedTuple（args / approved / rejected）
│                             #       _call_gate(gate, req)：兼容 callable gate 与 .request() 对象
│                             #       _apply_hitl(name, td, args, gate)：低风险/gate=None 直通；高风险走审批
│                             #       _safe_call(handler, args)：handler 抛 Exception 统一包 error envelope；
│                             #         BaseException（KeyboardInterrupt/SystemExit）不吞
│                             #   - run 流程：get → _apply_hitl 决策 → rejected 走 blocked envelope →
│                             #     否则 _safe_call 包异常 → approved 加 hitl_approved: True（见 ADR-0011 D1）
│                             # 默认注册 19 个工具（v0.2.3 后 +1：memory_recall，见 ADR-0004；
│                             #  v0.3 后 +1：memory_recall_by_tag，见 ADR-0007；
│                             #  v0.3.1 后 +2：memory_recall_by_title + memory_update_title，见 ADR-0012）；
│                             # evolution_enabled=false 时剩 17 个（去 propose_self_replace + terminate）
├── tools/blacklist.py         # 路径围栏 + 黑名单校验（含 runtime_state.json 路径）
├── tools/memory_tools.py      # 7 个 memory_* 工具（save + 5 recall + 1 update，见 ADR-0004 / ADR-0007 / ADR-0012）
├── tools/fs_tools.py          # read_file / list_dir / write_file
│                             # read_file v0.3+ 多返回 original_size（截断时与 size 不同），见 ADR-0007
├── tools/exec_tools.py        # run_cmd（独立模块，避免与 fs_tools 的纯文件操作混淆）
├── tools/web_search.py        # web_search + curl_url（5min 限流 + per-host throttle，v0.13.2 起走 util/web_search_rl.py；见 ADR-0024）
├── tools/diary_tools.py       # diary_write
├── tools/git_tools.py         # git_commit / git_push / snapshot_cleanup（medium，见 ADR-0007）
├── tools/evolve_tools.py      # propose_self_replace / terminate（高危，HITL 门控）
├── util/                      # 8 个模块：json_utils / jsonl_utils / subprocess_utils
│                             #          / diary_archive / git_helpers / heartbeat / http_parents
│                             #          / web_search_rl（v0.13.2 见 ADR-0024）
│                             #   heartbeat.py:   start_heartbeat_thread（v0.2.7，见 ADR-0008）
│                             #   http_parents.py: setup_http_parents_channel（v0.2.8，见 ADR-0009）
│                             #   web_search_rl.py: per-host 5min 限流（Throttle + ThrottleState + acquire_slot，v0.13.2，见 ADR-0024）
├── __tools_probe__.txt        # 47 bytes 探针残留（commit 91ea0843 同期，git tracked，
│                             #   当前不被 import，清理决策留给后续轮次，见 ADR-0011 D3）
├── scoring/                   # 占位包（v0.13.1 状态：持续仅 __pycache__/，缺 __init__.py，未 git tracked；
│                             #   v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 v0.4 评分基线；
│                             #   v0.13.1（ADR-0017）重新确认仍未建不删；ROADMAP 未把 scoring/
│                             #   提为 blocked，cleanup 决策留给后续轮次）
└── llm/                       # 占位包，目前仅 __init__.py
```

> 文件名约定（见 ADR-0005 / ADR-0006）：tools/ 按职责拆为 `fs_*`（文件）/ `exec_*`（执行）/
> `web_search`（网络搜索）/ `git_*` / `memory_*` / `diary_*` / `evolve_*`；
> v0.2.5 重命名 4 个文件 + 新增 `exec_tools.py`，详见 [ADR-0005](adr/0005-architecture-v0-sync-watchdog-and-tool-rename.md)。

工具总数：**19 个**（`evolution_enabled=false` 时剩 17 个；`propose_self_replace` + `terminate`
属 evolve_tools，由 HITL 门控的 high-risk 工具）。

## 三、注册工具（19）

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
| `memory_recall_by_title`  | low | 否 | 按 title 精确匹配召回 fact（newest first），v0.3.1 上线，见 ADR-0012 |
| `memory_update_title`     | low | 否 | 更新某条 fact 的 title；new_title=None 表示清空，v0.3.1 上线，见 ADR-0012 |
| `snapshot_cleanup`     | medium | 否 | 删除过期 snapshot（snapshot/side_git.cleanup_old_snapshots 暴露），v0.2.3+；见 ADR-0007 |
| `write_file`    | high | 是 | 写文件（路径围栏 + 黑名单校验） |
| `run_cmd`       | high | 是 | shell（30s 超时 + binary 黑名单 + pattern 黑名单） |
| `git_commit`    | high | 是 | git add+commit |
| `git_push`      | high | 是 | git push 到 origin |
| `propose_self_replace` | high | 是 | 金蝉脱壳：commit → push → 编译 → supervisor 切换 |
| `terminate`     | high | 是 | 优雅终止（supervisor 不再自动拉起） |

> §四 关键不变量里 17 → 19 与 §三 一致：5 个 recall 工具平级，补齐 `memory_recall_by_title` 后才是
> "5 种 recall 风格"（关键词 / 时间窗 / 频次 / 标签 / title），memory_tools.py 注释里也明说。

## 四、关键不变量

| 不变量 | 实现位置 |
| --- | --- |
| AGENTS.md / .env / runtime_state.json / .git/ 不可改 | `tools/blacklist.py` 路径黑名单（`write_blacklist`） |
| 危险 binary 不可用 | `config/settings.py::cmd_blacklist` + `cmd_blacklist_patterns`（v0.2.3 后增量） |
| HIL 通道是父母 | `hitl/gate.py`（仅响应人类父母指令） |
| 高危工具须审批 | `tools/registry.py::build_default_registry()` 无参调用；自动读 `Settings.evolution_enabled`，<br>`False` 时 unregister `propose_self_replace` + `terminate`（剩 17 个） |
| Diary 是真相 | `diary/YYYY-MM-DD.md` 人类可读 + `diary/turns/*` 结构化日志（Agent 不可自我粉饰） |
| 失败可回滚 | `snapshot/side_git.py` 每 turn tag + **两条清理路径**：<br>· **时间维** 两入口并存：<br>&nbsp;&nbsp;· `snapshot/age_cleanup.py::cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` —— 模块级（v0.11+，见 ADR-0019，推荐路径）<br>&nbsp;&nbsp;· `snapshot/side_git.py::cleanup_old_snapshots(max_age_days, dry_run)` —— 兼容 wrapper（v0.2+ 见 ADR-0003，inline 实现，与模块版功能等价）<br>· **数量维** `count_cleanup.cleanup_old_snapshots_by_count(max_count, dry_run)` 保留最新 N 个（v0.11，见 ADR-0016）<br>三条入口共享 `snapshot/_tag_index.py` 三个原语（`list_xragent_turn_tags` / `parse_xragent_turn_tags` / `delete_tags`，v0.5.x，见 ADR-0016），行格式 `%09` / `\t` 改一处时不再漂移。`snapshot_cleanup` 工具同时挂载两条清理路径供父母手动触发（见 ADR-0007） |
| Push 节流 | `push_interval_minutes=30`（autonomous 模式每 30 min 批量 push 一次） |
| 子进程异常可自愈 | `watchdog/supervisor.py` 定期读 `runtime_state.json` heartbeat，超过 `heartbeat_timeout_s` 未更新则判僵死、SIGTERM 后 fork 新子进程并 `bump_restart()`；累计 `restart_max_failures` 次失败后停。`runtime_state.json` 在 `write_blacklist` 里，Agent 不可改、自愈路径不被 Agent 干扰（见 ADR-0005 / ADR-0006） |
| read_file 契约演进 | `tools/fs_tools.py::read_file` v0.3+ 多返回 `original_size` 字段（截断场景下与 `size` 不同，让父母看到真实大小），见 ADR-0007 |
| tools/registry run 流程契约 | `tools/registry.py` v0.2.10 起：get → _apply_hitl 决策 → rejected 走 blocked envelope → 否则 _safe_call 包 Exception → approved 加 `hitl_approved: True`；handler 抛 BaseException（KeyboardInterrupt/SystemExit）不吞；hitl=low 或 gate=None 直通；callable gate 与 .request() 对象兼容（见 ADR-0011 D1） |
| Autonomous next_task 参数化冷却 | `autonomous.next_task(rng=None, window_s=DEFAULT_COOLDOWN_S)` v0.2.11 起：`window_s` 显式参数（默认 7200s），不污染 module 常量，便于测试短时间绕过冷却（见 ADR-0011 D4） |
| tools/registry 探针文件留痕 | `src/xragent/__tools_probe__.txt` v0.2.10 起：47 bytes 探针残留（commit 91ea0843 同期），git tracked，不被 import；清理决策留给后续轮次（见 ADR-0011 D3） |
| compression/hook.py import 清洁 | `compression/hook.py` v0.2.10 起：顶部 import 整理、无 noqa 残留；保持 hook 表可读性（见 ADR-0011 D5） |
| scoring/ 目录占位 | `src/xragent/scoring/` v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；v0.3.1 登记预留 v0.4 评分基线（ADR-0012 / ADR-0013 D6）；v0.13.1 重新确认仍未建不删，cleanup 决策留给后续轮次（见 ADR-0017） |
| web_search 5min 限流 + per-host throttle | `tools/web_search.py` v0.13.2 起：所有外部请求走 `util/web_search_rl.py::acquire_slot()`，per-host 5min 滑动窗口（`Throttle(60s window, 1 req/300s)`，命中 cooldown 时抛 `ThrottleState` 例外），curl_url 与 web_search 共用同一 throttle。落地：`_RATE_LIMIT = 300s`、`_WINDOW_S = 60s`、单进程内 `dict[str, ThrottleState]`；不走 `_RATE_LIMIT` 全局 hot-path，避免跨 host 误限。commit `e96001f8`，见 ADR-0024 |
| Autonomous journal 写盘 | `autonomous.next_task` / `record_done` v0.13.2 起：可选 `journal` 句柄注入（默认 `None`，不写盘）；注入时按 entry→round_done 双行 JSONL 写到 `memory/queue.jsonl`（与 cooldown key 共用路径），便于断点复盘 / 外部观测；测试通过 fake journal 断言（不污染实际路径） |
| Autonomous rng 显式参数化 | `autonomous.next_task(rng=None, journal=None, window_s=DEFAULT_COOLDOWN_S)` v0.13.2 起：`rng` 注入测试复现顺序、`journal` 注入观测（默认 None 不写盘），与 v0.2.11 `window_s` 参数（ADR-0011 D4）一致风格 —— 测试注入口集中、不污染 module 常量 |

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
| v0.2.7 | 架构 doc 同步：util/heartbeat.py 抽取（5 → 6 模块）+ memory schema 5.8 LRU（`last_accessed_ts` / `touch_fact` / `recall_lru`）。util/heartbeat.py 落地 commit `1a3d1d42`；doc 同步 commit `b78638d1` 被 `348d6f33` revert，round 158 close-out commit `381c5b8b` 被 `ed2bcb3b` revert；本 ADR-0008 重做 | ADR-0008 |
| v0.2.8 | 架构 doc 同步：util/http_parents.py 抽取（6 → 7 模块）+ tools/registry.build_default_registry 不再接 evolution_enabled 参数（自动读 Settings.evolution_enabled）。util/http_parents.py 落地 commit `7bd65f9a`；本 ADR-0009 doc sync | ADR-0009 |
| v0.2.9 | 架构 doc 同步：autonomous.py 加 `iter_tasks(stop_check)` 生成器（公开 API）+ 3 helper 公开化（task_queue_path / task_cooldown_key / _recent_titles）；hitl/gate.py 加 `_parse_stdin_line(line)` 纯函数 + `_DEFAULT_POLICIES: dict[str, Decision]` 收敛 2 个硬编码 if 分支。autonomous.py 落地 commit `7bd65f9a`；hitl/gate.py 落地 commit `ecc0d468`；本 ADR-0010 doc sync | ADR-0010 |
| v0.2.10 | 架构 doc 同步：tools/registry.py 内部结构展开（ToolDef dataclass + ToolRegistry 6 方法 + 5 module-level helper：_HitlRejected / _HitlOutcome / _call_gate / _apply_hitl / _safe_call + run 流程契约）+ `__tools_probe__.txt` 留痕（47 bytes 探针残留，git tracked 不被 import）+ compression/hook.py import 整理（顶部 import + 无 noqa）。`memory/manager.py.bak` 留痕（commit 43f68ada）→ 后续 CM commit `cecfef33` `git rm` 主动清理（见 ADR-0013 D8）。前次 commit `4f970a4d` 被 `6b7f3a99` revert；本 ADR-0011 重做 | ADR-0011 / ADR-0013 D8 |
| v0.2.11 | 架构 doc 同步：autonomous.next_task 加 `window_s` 参数（默认 `DEFAULT_COOLDOWN_S=7200`），测试可短时间绕过冷却、不污染 module 常量；落地 commit `65b75fae`；本 ADR-0011 D4 doc sync | ADR-0011 |
| v0.3.1 | 架构 doc 同步：工具面 19 个（+memory_recall_by_title +memory_update_title），§三表补 2 行 + §四不变量剩 17 个 + §二 memory_tools 注释 7 个 + §三表底 5 种 recall 风格 + §二模块清单 scoring/ 占位登记 + manager.py.bak 删除回溯。doc sync 落地 commit （本轮 ADR-0013）。ADR-0012 决策落地 + ADR-0013 增量 | ADR-0012 / ADR-0013 |
| v0.5 (✅ 部分) | memory schema 5.9 整理：`_migrate_v59()` 恢复 5.4/5.6 时代随 5.7 -456 行重构丢失的 `idx_facts_tags` / `idx_facts_title` 两个索引（DDL-only，幂等 CREATE INDEX IF NOT EXISTS）；配套补 `manager.recent()` method（不过滤 archived，用于调试 / 复盘）；evolve_tools.py 与 test_evolve_tools.py 契约对齐（`RUNTIME_STATE_KEY_*` 常量 + `dry_run` / `suppress_restart` 参数）。doc 同步：ADR-0014（设计）+ ADR-0015（实际落地）。未做：`SCHEMA_VERSION` 常量 bump（已知遗留，5.9 是 DDL-only 二次回填不增字段）、自动 rollback / 世代谱可视化 | ADR-0014 / ADR-0015 |
| v0.5.6 | `evolve/metamorphosis.py` `_check_compile` per-file timeout (30s) + concurrent；`exec_tools._safe_decode` 直测 15 cases 锁契约（任意值→str） | ADR-0016 |
| v0.5.7 | `memory/manager.py` `_safe_create_index` 加 PEP 604 hint + Google docstring（2 hints）；commit `a457993f` 同期 | ADR-0016 |
| v0.5.8 | `snapshot/_tag_index.py` 抽出 3 共享原语（`list_xragent_turn_tags` / `parse_xragent_turn_tags` / `delete_tags`），让 `cleanup_old_snapshots` + `cleanup_old_snapshots_by_count` 只剩策略；行格式 `%09` / `\t` 单点维护 | ADR-0016 |
| v0.5.9 | `snapshot/count_cleanup.py` 走 `_tag_index` helper（去掉 3 处 inline 重复）；保留/删除段用负索引 + 升序语义，无额外排序；commit `a59beb18` | ADR-0016 |
| v0.11 | SideGit snapshot cleanup 加 `dry_run` 参数（按时间 + 按数量两条路径都加），仅列候选不实际 `git tag -d`；`snapshot_cleanup` 工具同步暴露 `dry_run`。ROADMAP v0.11 ✅，commit `0247b56b` | ADR-0016 |
| v0.11+ (round 231) | `snapshot/age_cleanup.py` 抽出时间清理 standalone 镜像（与 `count_cleanup.py` 对称）；<br>模块级 `cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` 全部走 `_tag_index` helper；<br>`side_git.py::cleanup_old_snapshots` 保留为兼容 wrapper（未删除，inline 路径未改 caller→callee，留给后续 round）；<br>commit `fbe16191`<br>注：ROADMAP 未把本轮拆为独立 v0.12，**实际 ship 但版本号待 v0.12 决策时合并** | ADR-0019 |
| v0.13.2 (round 582) | `tools/web_search.py` 限流改造（5min cooldown + per-host throttle，命中抛 `ThrottleState`，不静默 swallow）+ `util/web_search_rl.py` 新增（Throttle + ThrottleState + acquire_slot，~40 行，规避 §二"过早抽象"门槛被 web_search + curl_url 双调用点对冲）<br>`autonomous.next_task` 加 `rng=None` + `journal=None` 显式参数（v0.13.2）：rng 注入测试复现顺序、journal 注入观测（默认 None 不写盘）；next_task 选 task 后写 entry、record_done 后写 round_done 到 `memory/queue.jsonl`（与 cooldown key 同路径）<br>doc 同步：ADR-0024（本轮 round 582）。未做：autonomous journal 双队列切分（current_done / queue_done 两表），已知遗留，决策留给后续轮次 | ADR-0024 |
