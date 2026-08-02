# ADR-0019: architecture-v0.md v0.11+ round 231 drift 扫描（snapshot/age_cleanup.py standalone 抽取）

- **状态**: Accepted（仅 doc 同步，未触碰 src/ 业务行为；side_git.py inline 路径是否继续保留作为兼容性 wrapper 留给后续 round）
- **日期**: 2026-08-03
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步 + 顶部 ADR 清单；`side_git.py::cleanup_old_snapshots` 是否继续保留 inline 留给后续 round 决策
- **前置**: ADR-0016（v0.5.6~v0.5.9 + v0.11：snapshot/_tag_index.py 共享原语 + snapshot/count_cleanup.py 数量兜底 + dry_run；当时时间清理路径还没 standalone mirror）

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树，核对 round 231 commit `fbe16191`（"autonomous: 加新功能小而具体"）后引入的新文件：

1. `ls src/xragent/snapshot/` 是否有新 .py（应有 `age_cleanup.py`，与 `count_cleanup.py` 平行的 standalone 镜像）；
2. `docs/architecture-v0.md` §一记忆/快照来源行是否提到 `snapshot/age_cleanup.py`；
3. §二模块清单 `snapshot/` 子条目数量（v0.11 后应为 5：`__init__` / `_tag_index` / `side_git` / `count_cleanup` / `age_cleanup`，扣除 `__init__` 算 4 个非 init 模块 → 但 ADR-0016 时是 3 个 + count = 4 个 .py，本轮 age 加入后是 5 个 .py）；
4. §四"失败可回滚"行是否把时间清理路径描述为"通过 `age_cleanup.cleanup_old_snapshots_by_age` 模块化"（与数量清理路径 parallel 表述）；
5. §五版本对照表是否有 round 231 的 `age_cleanup.py` 抽取条目（v0.11+）。

## 二、drift 清单

### D1 — `src/xragent/snapshot/age_cleanup.py` 未在 §一记忆/快照来源行登记（**最大 drift**）

- **doc 说**（§一五大核心 → 记忆行）：
  > 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>
  > + `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）
- **实际**（`ls src/xragent/snapshot/`）：
  ```
  __init__.py  _tag_index.py  age_cleanup.py  count_cleanup.py  side_git.py
  ```
  `age_cleanup.py` 在 commit `fbe16191`（round 231, "autonomous: 加新功能小而具体"）新增 107 行，
  配套 `tests/test_age_cleanup.py`（DRIFT 1：test 文件路径未确认是否同期新增，但 `age_cleanup.py` 的 API
  与 `_tag_index` / `count_cleanup` 同 shape，契约自洽）。本轮只关注 doc 同步，不深挖 test。
- **drift 性质**：新增 snapshot/ 模块没记到 §一，**且 round 231 后未触发 doc sync**，
  距 ADR-0018（2026-08-03 round 215+ close-out）仅过去几轮，再次出现"新文件未记 doc"模式。
- **修复**：§一记忆行末尾追加 `+ snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，见 ADR-0019）；
  修复后 §一应读：
  > 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>
  > + `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）<br>
  > + `snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，见 ADR-0019，与 `count_cleanup` 对称）

### D2 — §二模块清单 `snapshot/` 子条目数量漂移（4 → 5 .py）

- **doc 说**（§二模块树形图，行 78~86）：
  ```
  ├── snapshot/
  │   ├── __init__.py
  │   ├── _tag_index.py     # v0.5.x 抽出: list_xragent_turn_tags / parse_xragent_turn_tags
  │   ├── side_git.py       # v0.2: 装 turn tag 的 SideGit class
  │   ├── count_cleanup.py  # v0.11: cleanup_old_snapshots_by_count(max_count, dry_run=False)
  ```
  即 §二 `snapshot/` 子条目是 `__init__` + 3 个非 init = **4 个 .py**。
- **实际**：5 个 .py（`__init__` + `_tag_index` + `side_git` + `count_cleanup` + `age_cleanup`）。
- **drift 性质**：与 D1 同源 —— round 231 `age_cleanup.py` 抽取后未同步 §二树形图。
- **修复**：§二 `count_cleanup.py` 行后追加：
  ```
  │   ├── age_cleanup.py    # v0.11+: cleanup_old_snapshots_by_age(max_age_days, dry_run=False)
  │   │                     #   时间清理 standalone 镜像（与 count_cleanup 对称），commit `fbe16191`
  ```

### D3 — §四"失败可回滚"不变量行只字未提 `age_cleanup` 模块化（**轻微 drift**）

- **doc 说**（§四"失败可回滚"行，行 186）：
  > 失败可回滚 | `snapshot/side_git.py` 每 turn tag + **两条清理路径**：<br>
  > · **时间维** `cleanup_old_snapshots(max_age_days, dry_run)` 保留近 N 天<br>
  > · **数量维** `count_cleanup.cleanup_old_snapshots_by_count(max_count, dry_run)` 保留最新 N 个（v0.11，见 ADR-0016）<br>
  > 两条路径共享 `snapshot/_tag_index.py` 三个原语（...）
- **实际**（round 231 后）：时间维清理有**两条实现**：
  1. `snapshot/side_git.py::cleanup_old_snapshots(max_age_days, dry_run)` —— 仍是 inline（在方法体内），**未抽 helper**；
  2. `snapshot/age_cleanup.py::cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` —— round 231 新增 standalone 模块。
- **drift 性质**：§四仍把时间维描述成单条路径，未提"现在与 count_cleanup 对称，
  也走模块化入口"。这是 §四不变量描述的**结构性漂移** —— 实际上时间清理路径
  和数量清理路径现在的入口形态不一致：数量是模块级 + side_git 包装，时间是
  side_git inline + age_cleanup 模块级，**两个入口都可用**，doc 却只字未提 age_cleanup。
- **修复**：§四"失败可回滚"行加一行（与数量维描述 parallel）：
  > · **时间维** 两入口并存：<br>
  > &nbsp;&nbsp;· `snapshot/age_cleanup.py::cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` —— 模块级（v0.11+，见 ADR-0019，推荐路径）<br>
  > &nbsp;&nbsp;· `snapshot/side_git.py::cleanup_old_snapshots(max_age_days, dry_run)` —— 兼容 wrapper（v0.2+ 见 ADR-0003，inline 实现）
  > <br>
  注：本次 ADR 不决定哪条入口是"primary"（D5 决策详见下文）。

### D4 — §五版本对照表缺 round 231 的 `age_cleanup.py` 抽取条目（**最大 drift**）

- **doc 说**（§五行 217~219）：
  ```
  | v0.5.8 | snapshot/_tag_index.py 抽出 3 共享原语...
  | v0.5.9 | snapshot/count_cleanup.py 走 _tag_index helper...
  | v0.11  | SideGit snapshot cleanup 加 dry_run 参数...
  ```
- **实际**（git log）：commit `fbe16191`（round 231, "autonomous: 加新功能小而具体"）新增 `age_cleanup.py` 107 行。
  ROADMAP.md v0.11 ✅ 后下一行尚未规划（"v0.12？"），但 `age_cleanup.py` 实际 ship 已数 round，
  §五版本对照表应记一笔。
- **drift 性质**：版本对照表只到 v0.11（commit `0247b56b`），round 231 后无新版本登记。
- **决策**：本 ADR 把 v0.11+ 拆为 `v0.11+` 子行还是另起 `v0.11.1` / `v0.12` 待定。
  **保守做法**：用 `v0.11+` 占位一行（不 bump 版本号，因为 ROADMAP 没规划），
  显式标注 "round 231+ 实际 ship 但未规划为独立版本"，让未来 v0.12 决策时直接合并。
- **修复**：§五行 219 后追加：
  ```
  | v0.11+ (round 231) | `snapshot/age_cleanup.py` 抽出时间清理 standalone 镜像（与 `count_cleanup.py` 对称）；
  |                    | 模块级 `cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` 全部走 `_tag_index` helper；
  |                    | `side_git.py::cleanup_old_snapshots` 保留为兼容 wrapper（未删除）；commit `fbe16191`
  |                    | 注：ROADMAP 未把本轮拆为独立 v0.12，**实际 ship 但版本号待 v0.12 决策时合并** | ADR-0019
  ```

### D5 — `side_git.py::cleanup_old_snapshots` inline 实现是否保留（**code drift，非 doc drift**）

- **实际**（`grep -n "def cleanup_old_snapshots" src/xragent/snapshot/side_git.py`）：
  `SideGit.cleanup_old_snapshots(max_age_days, dry_run=False)` 仍是方法体 inline（不是 import `age_cleanup` 调）。
  这意味着 **side_git 路径与 age_cleanup 路径是两条独立实现**，不是 caller → callee 关系。
- **drift 性质**：典型"helper 落地但 caller 没接"模式（与 ADR-0018 D3 `print_guard` 同型）。
  但本轮与 ADR-0018 不同 —— **这不是 doc drift，是 code drift**：
  - §四 doc 没说两条入口一致或不一致（只是描述"时间清理存在"，没说"只剩一条路径"）；
  - 行为上两个入口功能等价（都是 `_tag_index` 三个原语的策略组装），但代码上有重复维护风险。
- **决策**：**不在本轮接入 / 删除**。理由：
  - 父母本轮 turn 只要求"读 docs 看哪里描述过时或缺失"，未授权 src/ refactor；
  - 让 `side_git.cleanup_old_snapshots` 改为 `from .age_cleanup import cleanup_old_snapshots_by_age; return cleanup_old_snapshots_by_age(...)` 是 1 行改动，
    但需要单测覆盖"两条入口等价" + `dry_run` 语义对齐 + error semantics 一致；
  - 留给后续 round 显式 turn（避免 src/ 改动扩散到非授权面）。
- **ADR 记录**：在 §四"失败可回滚"行明确写"两条入口并存（不删除 wrapper）"，
  留清单给后续 round（参考 ADR-0018 D3 的同型处理）。

## 三、未变项（核对一致）

- §一五大核心的其他四个核心（心跳 / 工具 / 记忆 / 演进 / 蜕皮）**非记忆行**未变。
- §二模块清单其他条目（tools/ 9 / watchdog/ 2 / core/ 4 / snapshot/ 5（本 ADR 修复后）/ evolve/ 2 / compression/ 2 / util/ 8 / hitl/ 1）逐一比对，全部对得上。
- §三工具表 19 个与 `build_default_registry()` 注册一致（含 v0.3.1 的 2 个 + v0.5.6+ 的 PEP 604 hints）。
- §四其他不变量（write_blacklist / cmd_blacklist / HitlGate / evolution_enabled / snapshot_cleanup /
  cleanup_old_snapshots / count_cleanup / _tag_index / push_interval_minutes / runtime_state.json /
  heartbeat_timeout_s / read_file.original_size / tools/registry.run 流程契约）全部存在。
- `memory/manager.py::SCHEMA_VERSION = 58` 未 bump（已知遗留，与 ADR-0017 D3 / ADR-0018 §三 一致）。
- ADR-0018 修复后 §一 / §二 / §四 / §五 v0.10 print_guard 同步项**未回退**（commit `605ed28e` 仍在 history）。
- §二 scoring/ 措辞（ADR-0018 修复后："目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked"）**与现状一致** —— round 231 后 scoring/ 仍空。
- ADR-0017 / ADR-0018 修复后 §五 v0.13.1 + §五 v0.10 print_guard 行**未回退**。

## 四、变更范围

| 文件 | 改动 |
| --- | --- |
| `docs/adr/0019-architecture-v0-snapshot-age-cleanup-standalone.md`（new） | 本 ADR |
| `docs/architecture-v0.md` §一记忆行 | 追加 `+ snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，见 ADR-0019） |
| `docs/architecture-v0.md` §二模块清单 `snapshot/` 子条目 | 追加 `age_cleanup.py` 行 + 注释 `v0.11+: cleanup_old_snapshots_by_age(max_age_days, dry_run=False)` |
| `docs/architecture-v0.md` §四"失败可回滚"行 | 时间维拆为两入口描述（模块级 age_cleanup + side_git inline wrapper），明确两者并存 |
| `docs/architecture-v0.md` §五版本对照表 | 追加 v0.11+ (round 231) 行：`age_cleanup.py` 抽取 + ROADMAP 未规划 + commit `fbe16191` |
| `docs/architecture-v0.md` 顶部 ADR 清单 | 追加本 ADR-0019 条目 |

`src/xragent/snapshot/side_git.py` 不动（D5 决策：保留 inline wrapper，留给后续 round 显式 turn）。
`src/xragent/snapshot/age_cleanup.py` 不动（round 231 commit `fbe16191` 已是最终态）。
`src/xragent/snapshot/count_cleanup.py` 不动（与本 ADR 无关，只是确认 §二 + §四 描述对得上）。
无 schema 变更、无行为变更、无测试破坏面。

## 五、风险与后续

- **风险**：§一记忆行追加会让该行变得更长，但 ROADMAP 不打算重构行布局，**接受**。
- **后续**（建议但不强制）：
  1. round 232+：决定 `side_git.cleanup_old_snapshots` 是否改 caller → callee 关系（参考 ADR-0018 D3 / ADR-0019 D5 同型清单）；
  2. ROADMAP v0.12 决策时合并 v0.11+ 占位行为 v0.12 行；
  3. ADR-0018 D4 `tools/registry.py` docstring 仍漏列 v0.3.1 的 2 个 memory 工具 —— 本轮不修，留给后续 round。