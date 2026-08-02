# ADR-0018: architecture-v0.md v0.10 round 215+ drift 扫描（util/print_guard + scoring/ 二次清空）

- **状态**: Accepted（仅 doc 同步，未触碰 src/ 业务行为；print_guard helper 与 main.py 接入留给后续 round）
- **日期**: 2026-08-03
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步 + 顶部 ADR 清单；print_guard helper 是否被 main.py 接入、scoring/ 是否补 `__init__.py` 都**留给后续 round** 决策
- **前置**: ADR-0017（round 213+ doc-vs-code drift 扫描；scoring/ 状态首次正式记录）

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树，核对：
1. `src/xragent/util/` 文件清单 vs doc §一 / §二 util/ 子条目；
2. `src/xragent/scoring/` 当前空状态 vs doc §二 / §四 scoring/ 描述（ADR-0017 落地后又一轮 close-out 是否进一步清空）；
3. `main.py` 是否已接入 `util.print_guard` helper（commit `605ed28e` 引入 helper 后的契约落地状态）；
4. §五 版本对照表 v0.10 条目是否覆盖 round 203 `print_guard` 抽取。

## 二、drift 清单

### D1 — `src/xragent/util/print_guard.py` 缺失（doc §一 / §二 / §五 三处失真，**最大 drift**）

- **doc 说**（§一五大核心 + §二模块清单 util/ 子条目）：
  > 当前 **7 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` /
  > `diary_archive` / `git_helpers` / `heartbeat` / `http_parents`
  > （v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；
  > v0.2.8 +http_parents，见 ADR-0009）
- **实际**（`ls src/xragent/util/`）：**8 个模块**：
  ```
  __init__.py  diary_archive.py  git_helpers.py  heartbeat.py
  http_parents.py  json_utils.py  jsonl_utils.py  print_guard.py
  subprocess_utils.py
  ```
  `print_guard.py` 在 commit `605ed28e`（round 203, "autonomous: 重构抽公共函数"）新增 43 行，
  同期 `tests/test_print_guard.py` 171 行 14 cases 全过。
- **§五版本对照表 v0.10 条目**只字未提 `print_guard` 抽取：
  > v0.10 — Interactive TUI Channel（CT0 强制）
  > scripts/chat (HTTP 父母通道终端化) / ANSI 色彩 / readline 历史 /
  > HTTP /tools / /memory/recent / /generations / /metamorphose 端点 /
  > 流式输出 / 中断当前 round / 会话历史持久化 / 自动补全
- **drift 性质**：新增 util/ 模块没记到 doc 任何一处（§一 / §二 / §五 三处全部漏），
  且 v0.10 round 203 commit 引入后从未触发 doc sync。
- **修复**：
  1. §一 + §二 util/ 子条目 7 → 8 modules，加 `print_guard.py` + 引用 ADR-0018；
  2. §一util/ 注释里 heartbeat / http_parents 注释后追加 "v0.10 round 203 +print_guard（见 ADR-0018）"；
  3. §五 v0.10 条目下追加一行：「- [x] `util/print_guard.py` 抽取（main.py `try/except Exception + print failed` 模板抽 helper；commit `605ed28e` round 203；tests/test_print_guard.py 14 cases 全过锁契约；**main.py 实际未接入 — 见 ADR-0018 D3**）。
- **决策**：**不主动改 main.py 接入 print_guard**。理由：
  - 父母本轮 turn 只要求"读 docs 看哪里描述过时或缺失"，未要求 refactor src/；
  - main.py 行 275 / 279 / 345 / 356 / 368 / 378 仍有 `except Exception as e: print(f"[autonomous] ... failed: ...", flush=True)` 模板；
  - 接入需要逐处判断 fallback 语义（task gen → sleep + continue vs commit → 跳过副作用但 record_done vs push → 跳过 last_push_ts 更新），
    属业务策略决策，**留给后续 round 显式 turn**（避免 src/ 改动扩散到非授权面）。

### D2 — `src/xragent/scoring/` 二次清空（doc §二 / §四 scoring/ 描述轻微漂移）

- **doc 说**（§二 + §四，ADR-0017 round 213+ 落地后）：
  > `scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；
- **实际**（`ls src/xragent/scoring/`）：目录存在但**完全空**（既无 `__pycache__/` 也无 `__init__.py`）。
  对比 `ls src/xragent/llm/` 仍有 `__init__.py` + `__pycache__/`，证明 scoring/ 是真"二次清空"，
  不是落描述时刚好 `__pycache__/` 被 `__pycache__` 缓存清理解。
- **drift 性质**：ADR-0017 落地后到本 round 间又经历至少 5 轮 close-out
  （`e9f55871` round 215+ / `3972331c` round 214+ / `7060eb51` round 213+ /
  `dab2025d` round 212+ / `c07396e8` round 211+），round 215+ close-out commit 显式
  提到"src/ 0 diff"但环境清理路径上 `__pycache__/` 跟着 git clean / 重建索引被清掉了。
- **修复**：
  §二 + §四 scoring/ 措辞改为「目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked；
  保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**」，
  与 ADR-0017 D1 决策一致（不补 `__init__.py`、不建任何占位 .py）。

### D3 — `util/print_guard` helper 实际未被 main.py 接入（**新发现**，代码契约 vs 业务契约）

- **helper 设计意图**（`util/print_guard.py` docstring）：
  > `main.py::cmd_autonomous` 里有 3 处重复的
  > `except Exception as e: print(f"[autonomous] <X> failed: {e}", flush=True)`
  > 模式（push / task gen / commit），抽到 `print_guard` helper。
- **实际**（`grep -rn "print_guard" src/`）：**main.py 与 `src/` 其他模块都未导入 `print_guard`**，
  仅 `tests/test_print_guard.py` 使用（lock API contract）。`src/xragent/main.py` 行 345 / 356 / 368 / 378
  仍有 inline `except Exception as e: print(f"[autonomous] ... failed: ...", flush=True)` 4 处。
- **drift 性质**：helper 已 ship 但 caller 没接 —— 是典型的"helper 落地但 integration 漏"。
  不算 doc drift，是 **code drift**（helper 与 caller 不同步）。
- **决策**：**不在本轮接入**。理由同 D1 末段。
  本 ADR 仅记录这件事 + 留下"main.py 4 处待接入"的清单，
  留给后续 round 显式 turn（避免 src/ 改动扩散到非授权面）。
  接入点草案：
  - main.py:345（push 失败）→ fallback: 跳过 `last_push_ts = now`
  - main.py:356（commit 失败）→ fallback: 跳过 commit-only 副作用但仍 `record_done`
  - main.py:368 + 378（task gen 失败）→ fallback: sleep 60s + continue
  注：main.py:275 + 279 不在 `cmd_autonomous` 内（应在 `cmd_serve` 或 main entry），
  是否接入需逐处判断语义，本 ADR 不强行定义。

### D4 — `tools/registry.py::build_default_registry` in-source docstring 漏列 v0.3.1 新增 2 个工具（**沿袭 ADR-0017 D2**，本轮仍未修复）

- **doc 状态**：architecture-v0.md §三已记 19 个工具（含 v0.3.1 的 2 个），**doc 自身 OK**。
- **in-source 状态**（`tools/registry.py:182-198`）：docstring 低风险组还停留在 v0.2.6 的 8 个：
  ```
  * low: read_file / list_dir / memory_save / memory_recall /
    memory_recall_range / memory_top_frequent / memory_recall_by_tag /
    diary_write
  ```
  漏了 `memory_recall_by_title` + `memory_update_title`。
- **drift 性质**：in-source docstring vs 注册表不一致（与 ADR-0017 D2 同期发现，但本轮仍未触碰）。
- **决策**：**本轮不修 in-source docstring**。理由：
  - 父母本轮 turn 限定 docs drift 范围，未授权 src/ 改动；
  - 单独修 docstring 是"无 src/ 行为改动"的低风险动作，但本 round 已集中修 doc，
    修 in-source 会让 commit 不纯（混 doc 同步 + src/ 字符串修改）；
  - 留给下一轮显式 docstring sync turn 处理（沿用 ADR-0017 D2 的修复方案，原文已写）。

## 三、未变项（核对一致）

- §一五大核心的实现位置全部仍在（`core/dream.py` / `hitl/gate.py` / `tools/blacklist.py` /
  `memory/manager.py` + `snapshot/*` / `evolve/*` + `autonomous.py` + `watchdog/supervisor.py`）。
- §二模块清单除 util/ + scoring/ 外其他条目逐一比对：`tools/` 9 个 .py、
  `watchdog/` 2 个、`core/` 4 个、`snapshot/` 3 个、`evolve/` 2 个、`compression/` 2 个、`util/` 8 个（**本 ADR 修复后**）、`hitl/` 1 个 —— 全部对得上。
- §三工具表 19 个与 `build_default_registry()` 注册一致（含 v0.3.1 的 2 个）；
  evolution_enabled=false 时剩 17 个（unregister `propose_self_replace` + `terminate`）也一致。
- §四关键不变量的 13 条引用全部存在（write_blacklist / cmd_blacklist / HitlGate /
  evolution_enabled / snapshot_cleanup / cleanup_old_snapshots / count_cleanup /
  _tag_index / push_interval_minutes / runtime_state.json / heartbeat_timeout_s /
  read_file.original_size / tools/registry.run 流程契约）。
- `memory/manager.py::SCHEMA_VERSION = 58` 未 bump（已知遗留，5.9 是 DDL-only 二次回填，
  与 ADR-0017 D3 一致）。

## 四、变更范围

| 文件 | 改动 |
| --- | --- |
| `docs/adr/0018-architecture-v0-util-print-guard-and-scoring-empty.md`（new） | 本 ADR |
| `docs/architecture-v0.md` §一 util/ 列表 | 7 → 8 modules，加 `print_guard.py`；注释加 `v0.10 round 203 +print_guard（见 ADR-0018）` |
| `docs/architecture-v0.md` §二 util/ 子条目 | 7 → 8 modules |
| `docs/architecture-v0.md` §二 scoring/ 描述 | "持续仅 `__pycache__/`，缺 `__init__.py`" → "目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked；保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**" |
| `docs/architecture-v0.md` §四 scoring/ 不变量行 | 同上 |
| `docs/architecture-v0.md` §五 v0.10 条目 | 追加 print_guard 抽取行（commit `605ed28e`）+ 标注"main.py 实际未接入 — 见 ADR-0018 D3" |
| `docs/architecture-v0.md` 顶部 ADR 清单 | 追加本 ADR-0018 条目 |

`src/xragent/main.py` 不动（D3 决策：留给后续 round 显式 turn）。
`src/xragent/tools/registry.py` docstring 不动（D4 决策：留给后续 round）。
`src/xragent/scoring/` 不动（D2 决策：不补 `__init__.py`、不建占位 .py）。
无 schema 变更、无行为变更、无测试破坏面。