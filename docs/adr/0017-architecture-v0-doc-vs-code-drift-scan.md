# ADR-0017: architecture-v0.md doc-vs-code drift 扫描（round 213+）

- **状态**: Accepted（仅 doc 同步，未触碰 src/ 业务行为）
- **日期**: 2026-08-03
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 与 in-source docstring 同步；不引入新行为、不 bump schema

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树，核对：
1. §一 五大核心的实现位置是否仍在；
2. §二 模块清单里 `src/xragent/scoring/` 实际状态；
3. §三 工具表 19 个是否都还在 `tools/registry.py::build_default_registry` 注册；
4. §四 不变量引用的具体函数 / 常量是否一致；
5. §一 memory schema 5.9 vs `memory/manager.py::SCHEMA_VERSION` 常量。

## 二、drift 清单

### D1 — `src/xragent/scoring/` 目录实际为空（doc §二/§四失真）

- **doc 说**（§二末尾 + §四不变量表）：
  > `scoring/` 占位包（v0.3.1 状态：仅 `__pycache__/`，缺 `__init__.py`，未 git tracked）；
  > 预留 v0.4 评分基线（见 ADR-0012 / ADR-0013 D6）
- **实际**（`ls src/xragent/scoring/`）：目录存在但**完全空**（既无 `__pycache__/` 也无 `__init__.py`）。
  `git ls-files src/xragent/scoring/` 也无输出，确未 git tracked。
- **drift 性质**：描述性，目录占位的"空"程度比 doc 写的还要彻底。
  v0.5 / v0.11 之后清理 history round 可能顺手把 `__pycache__/` 也删了，导致
  连"占位 Python 包"的痕迹都没了。
- **修复**：doc §二 + §四把 scoring/ 描述从"仅 `__pycache__/`"改为"目录存在但完全空（含 `__pycache__/` 已无残留）"。
- **决策**：**不补 `__init__.py`、不建任何占位 .py**。
  scoring/ 在 v0.3.1 之后没有任何实质进展（ROADMAP.md 也未把 v0.4 评分基线
  推进到 planned 之外），主动占位反而会引入虚假"已有内容"的信号；
  保留空目录以备后续 round 真要写评分基线时直接 `touch __init__.py` 即可。

### D2 — `tools/registry.py::build_default_registry` in-source docstring 漏列 2 个 v0.3.1 新增工具

- **doc 说**（§三表）：19 个工具，包括 `memory_recall_by_title` + `memory_update_title`（v0.3.1，见 ADR-0012）。
- **实际**（`tools/registry.py:182-198`）：19 个工具确实全部注册（含上述 2 个），
  **但 `build_default_registry` 的 in-source docstring** 低风险分组还停留在 v0.2.6 的 8 个：
  ```
  * low: read_file / list_dir / memory_save / memory_recall /
    memory_recall_range / memory_top_frequent / memory_recall_by_tag /
    diary_write
  ```
  漏了 `memory_recall_by_title` 和 `memory_update_title` 两个 v0.3.1 上线的工具。
- **drift 性质**：in-source docstring 与真实注册表不一致；外部读者只看 docstring
  会以为低风险只有 8 个、按 8 个算 `evolution_enabled=false` 时剩 15 个（错）。
- **修复**：把 docstring 低风险组补齐为 10 个：
  ```
  * low: read_file / list_dir / memory_save / memory_recall /
    memory_recall_range / memory_top_frequent / memory_recall_by_tag /
    memory_recall_by_title / memory_update_title / diary_write
  ```
  注：medium 组 3 个 + high 组 6 个已在 docstring，无需改。

### D3 — `memory/manager.py::SCHEMA_VERSION = 58` vs 实际有效 5.9（**非新发现，已记**）

- doc §一表格 + 注释已显式承认：
  > 注：常量 `SCHEMA_VERSION = 58` 未 bump 是已知遗留（5.9 migration 是 DDL-only 的二次回填，不改字段），有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准
- 本轮扫描再次确认 `_migrate_all()` 跑到 `_migrate_v59()`（5.9 恢复 5.4/5.6 时代丢失的 `idx_facts_tags` / `idx_facts_title`）。
- **决策**：**不 bump** `SCHEMA_VERSION`。
  这是已记录的故意遗留（bump 会触发"看似新增列"假象，掩盖 5.9 是 DDL-only 二次回填的事实）。
  本 ADR 仅重申该决策，不新增修复动作。

## 三、未变项（核对一致）

- §一五大核心的实现位置全部仍在（`core/dream.py` / `hitl/gate.py` / `tools/blacklist.py` / `memory/manager.py` + `snapshot/*` / `evolve/*` + `autonomous.py` + `watchdog/supervisor.py`）。
- §二模块清单其他条目逐一比对：util/ 7 个模块、`tools/` 9 个 .py、`watchdog/` 2 个、
  `core/` 4 个、`snapshot/` 3 个、`evolve/` 2 个、`compression/` 2 个 —— 全部对得上。
- §三工具表 19 个与实际 `build_default_registry` 注册一致（含 v0.3.1 的 2 个）。
- §四关键不变量的 13 条引用全部存在：`write_blacklist` / `cmd_blacklist` / `HitlGate` /
  `evolution_enabled` / `snapshot_cleanup` 工具 / `cleanup_old_snapshots` /
  `count_cleanup.cleanup_old_snapshots_by_count` / `snapshot/_tag_index.py` /
  `push_interval_minutes` / `runtime_state.json` / `heartbeat_timeout_s` /
  `read_file.original_size` / `tools/registry.run` 流程契约。
- §五版本对照表 v0.5.x / v0.11 各条目与 git log 一致。

## 四、变更范围

| 文件 | 改动 |
| --- | --- |
| `docs/architecture-v0.md` §二 scoring/ 注释 | "仅 `__pycache__/`，缺 `__init__.py`，未 git tracked" → "目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked；保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**" |
| `docs/architecture-v0.md` §四 scoring/ 不变量行 | 同上 |
| `tools/registry.py::build_default_registry` docstring | low 组从 8 个补到 10 个，加 `memory_recall_by_title` + `memory_update_title` |
| `docs/architecture-v0.md` 顶部 ADR 清单 | 追加本 ADR-0017 条目 |

`src/xragent/memory/manager.py` 不动（SCHEMA_VERSION 故意不 bump，详 D3）。
无 schema 变更、无行为变更、无测试破坏面。