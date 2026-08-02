# ADR-0020: architecture-v0.md round 235 close-out — ADR-0018 D1/D2 doc 修复实际落地 + ADR-0019 D1-D5 全部已落地确认

- **状态**: Accepted（仅 doc 同步 + §五版本对照表追加 v0.10 行；不触碰 src/）
- **日期**: 2026-08-03
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步 + 顶部 ADR 清单 + §五版本对照表 v0.10 行追加；ADR-0018 D3 / D4 的 code drift 仍留给后续 round 显式 turn
- **前置**: ADR-0017（round 213+ doc-vs-code drift 扫描）、ADR-0018（v0.10 round 215+ close-out doc sync 设计）、ADR-0019（v0.11+ round 231 age_cleanup standalone 抽取）

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树，核对：

1. ADR-0018 commit `59387b4d` (round 215+) 描述的修复方案（D1 改 §一/§二/§五 + D2 改 §二/§四 scoring/ 措辞）是否已实际落到 doc；
2. ADR-0019 commit `753f63a1` (round 231) 描述的修复方案（D1-D5）是否已实际落到 doc；
3. §五版本对照表 v0.10 行是否存在（ADR-0018 D1 修复方案第 3 步要求追加）；
4. 顶部 ADR 索引行 19-20 措辞是否与现实 commit / doc 状态一致。

## 二、drift 清单

### D1 — ADR-0018 D1 描述的修复方案**未实际落地**（**最大 drift**，跨 20 round 失真）

- **ADR-0018 commit `59387b4d`** (round 215+, 标题"autonomous: 写 ADR 设计决策 (round 215)") 实际上**只新增了 ADR 文本本身**（1 file changed, 135 insertions），**一字未改 `docs/architecture-v0.md`**。
- **ADR-0018 D1 修复方案**要求：
  1. §一 + §二 util/ 子条目 7 → 8 modules，加 `print_guard.py` + 引用 ADR-0018；
  2. §一 util/ 注释里 heartbeat / http_parents 注释后追加 "v0.10 round 203 +print_guard（见 ADR-0018）"；
  3. §五 v0.10 条目下追加一行：「`util/print_guard.py` 抽取（main.py `try/except Exception + print failed` 模板抽 helper；commit `605ed28e` round 203；tests/test_print_guard.py 14 cases 全过锁契约；**main.py 实际未接入 — 见 ADR-0018 D3**）」。
- **本轮（round 235）实测**（`grep -n "print_guard\|8 个模块\|7 个模块" docs/architecture-v0.md`）：
  - §一行 52：「当前 **7 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` / `heartbeat` / `http_parents`」 — 仍是 7 个名字（`print_guard.py` 漏列）
  - §二行 131：`util/                      # 7 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents` — 仍是 7 个名字
  - §五行：grep `v0.10` 只匹配 ADR-0018 索引行（行 20），**§五版本对照表本身没有 v0.10 行** —— 与 ADR-0018 D1 修复方案第 3 步"§五 v0.10 条目下追加"冲突
- **drift 性质**：ADR-0018 Accepted 时声称"doc sync 已 ship"但实际只写了 ADR 文本；从 round 215+ 到 round 235（跨 20 round）经历了 11+ 轮 close-out（`a9bdf7b8` round 230+ / `da1327dc` round 234+ / `9b87086c` round 233+ / `165fb1c0` round 232+ / `753f63a1` round 231 / `911145f2` round 231+ / `fbe16191` round 231 / `e9f55871` round 215+ / `3972331c` round 214+ / `7060eb51` round 213+ / `dab2025d` round 212+ / `c07396e8` round 211+ 等）每轮都标 `src/ 0 diff`，但从没人回头补 doc。
- **修复**（本轮实际执行）：
  1. §一行 52-54 改 `7 个模块` → `8 个模块`，加 `print_guard.py` 注释：`(v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；v0.2.8 +http_parents，见 ADR-0009；v0.10 round 203 +print_guard，见 ADR-0018 / ADR-0020)`；
  2. §二行 131-132 改 `7 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents` → `8 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents / print_guard` 并加 `print_guard.py` 注释行；
  3. §五行 v0.11+ (round 231) 行（行 225）**之前**插入新行 v0.10 (round 203 + 215+ close-out) 描述 print_guard 抽取 + main.py 未接入提示；
  4. 顶部 ADR 索引行 20 措辞修正：从「commit `59387b4d`」改为「commit `59387b4d`（仅 ADR 文本；doc 修复实际由本 ADR-0020 round 235 执行，跨 20 round 补落）」，让索引与现实一致。

### D2 — ADR-0018 D2 描述的修复方案**未实际落地**（scoring/ 二次清空措辞跨 20 round 仍是旧表述）

- **ADR-0018 D2 修复方案**要求：
  §二 + §四 scoring/ 措辞改为「目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked；保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**」。
- **本轮实测**（`ls src/xragent/scoring/`）：目录存在但**完全空**（既无 `__pycache__/` 也无 `__init__.py`，对比 `ls src/xragent/llm/` 仍有 `__init__.py` + `__pycache__/`，证明是真"二次清空"）。
- **doc 当前**（§二行 137-139 + §四行 199）仍写：
  > 「`scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；v0.3.1（ADR-0012 / ADR-0013 D6）登记预留 v0.4 评分基线；v0.13.1（ADR-0017）重新确认仍未建不删；ROADMAP 未把 scoring/ 提为 blocked，cleanup 决策留给后续轮次）」
  > 「`src/xragent/scoring/` v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；v0.3.1 登记预留 v0.4 评分基线（ADR-0012 / ADR-0013 D6）；v0.13.1 重新确认仍未建不删，cleanup 决策留给后续轮次（见 ADR-0017）」
- **drift 性质**：从 round 215+ 到 round 235 跨 20 round，措辞停留在 v0.13.1 ADR-0017 落地的"持续仅 `__pycache__/`"，但 `__pycache__/` 已经在后续 close-out 链的 git clean / 缓存清理中**真的没了**。
- **修复**（本轮实际执行）：
  §二 + §四 scoring/ 措辞改为「目录存在但**完全空**（含 `__pycache__/` 已无残留），未 git tracked；保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**（与 ADR-0017 D1 决策一致）」，并在末尾加「v0.13.1+ 二次清空（round 235 close-out 实测：连 `__pycache__/` 也已无残留，见 ADR-0017 / ADR-0018 / ADR-0020）」。

### D3 — ADR-0018 D3（util/print_guard helper 未被 main.py 接入）**仍未修**（沿袭 ADR-0018 决策留给后续 round）

- **doc 状态**：本轮 §五 v0.10 行追加的 print_guard 子行**会显式标注**「main.py 实际未接入 — 见 ADR-0018 D3 / ADR-0020 D3」，让 doc 自身承认这件事存在。
- **code 状态**（`grep -rn "print_guard" src/`）：main.py 与 `src/` 其他模块**仍未导入 print_guard**；仅 `tests/test_print_guard.py` 使用。`src/xragent/main.py` 仍有 inline `except Exception as e: print(f"[autonomous] ... failed: ...", flush=True)` 4+ 处。
- **决策**：**本轮仍不接入**。沿袭 ADR-0018 D3 决策（父母本轮 turn 只要求 doc 同步，未授权 src/ 改动；接入需逐处判断 fallback 语义属业务策略决策）。本 ADR-0020 仅在 doc §五 v0.10 行**显式标注**"main.py 实际未接入"，并把"main.py 4+ 处待接入清单"原样从 ADR-0018 D3 抄到本 ADR D3，留给后续 round 显式 turn。
- 接入点草案（沿袭 ADR-0018 D3）：
  - main.py:345（push 失败）→ fallback: 跳过 `last_push_ts = now`
  - main.py:356（commit 失败）→ fallback: 跳过 commit-only 副作用但仍 `record_done`
  - main.py:368 + 378（task gen 失败）→ fallback: sleep 60s + continue
  - main.py:275 + 279（非 `cmd_autonomous` 内，`cmd_serve` 或 main entry）→ 是否接入需逐处判断语义

### D4 — tools/registry.py docstring 漏列 v0.3.1 的 2 个工具（沿袭 ADR-0017 D2 / ADR-0018 D4，本轮仍未修）

- **doc 状态**：architecture-v0.md §三已记 19 个工具，**doc 自身 OK**。
- **in-source 状态**（`tools/registry.py:182-198`）：docstring 低风险组还停留在 v0.2.6 的 8 个，漏了 `memory_recall_by_title` + `memory_update_title`。
- **决策**：**本轮仍不修 in-source docstring**。沿袭 ADR-0017 D2 / ADR-0018 D4 决策（父母本轮 turn 限定 doc 范围，未授权 src/ 改动）。留给下一轮显式 docstring sync turn。

## 三、ADR-0019 D1-D5 全部已落地确认（无需再改）

对照 ADR-0019 commit `753f63a1` (round 231, 标题"docs(arch): ADR-0019 + sync architecture-v0.md round 231 age_cleanup drift (src/ 0 diff)") 的描述：
- **D1** §一记忆行未登记 `snapshot/age_cleanup.py` —— **已落地**：§一行 30 第三段已写「`snapshot/age_cleanup.py`（v0.11+ 时间清理 standalone 镜像，与 `count_cleanup.py` 对称，见 ADR-0019）」
- **D2** §二模块清单 snapshot/ 子条目 4 → 5 .py —— **已落地**：§二已写「`snapshot/age_cleanup.py    # v0.11+ (round 231): cleanup_old_snapshots_by_age(max_age_days, dry_run=False)...`」
- **D3** §四"失败可回滚"行未提 age_cleanup 模块化 —— **已落地**：§四已写「**时间维** 两入口并存：`snapshot/age_cleanup.py::cleanup_old_snapshots_by_age(...)` —— 模块级（v0.11+，见 ADR-0019，推荐路径）」+「`snapshot/side_git.py::cleanup_old_snapshots(max_age_days, dry_run)` —— 兼容 wrapper（v0.2+ 见 ADR-0003）」
- **D4** §五版本对照表缺 round 231 age_cleanup 抽取条目 —— **已落地**：§五行 225 已写「v0.11+ (round 231) | `snapshot/age_cleanup.py` 抽出时间清理 standalone 镜像...commit `fbe16191`...见 ADR-0019」
- **D5** side_git.py::cleanup_old_snapshots inline 保留 —— **故意保留**（code drift 不修，与 ADR-0019 D5 一致）

**结论**：ADR-0019 D1-D5 全部已在 round 231 commit `753f63a1` 落地，本 ADR-0020 不再重复改。

## 四、未变项（核对一致）

- §一五大核心的实现位置全部仍在（`core/dream.py` / `hitl/gate.py` / `tools/blacklist.py` / `memory/manager.py` + `snapshot/*` / `evolve/*` + `autonomous.py` + `watchdog/supervisor.py`）。
- §二模块清单除 util/ 7→8 + scoring/ 措辞外其他条目逐一比对：`tools/` 9 个 .py、`watchdog/` 2 个、`core/` 4 个、`snapshot/` 5 个（含 age_cleanup）、`evolve/` 2 个、`compression/` 2 个、`util/` 8 个（本 ADR 修复后）、`hitl/` 1 个 —— 全部对得上。
- §三工具表 19 个与 `build_default_registry()` 注册一致；evolution_enabled=false 时剩 17 个也一致。
- §四关键不变量的 13 条引用全部存在（write_blacklist / cmd_blacklist / HitlGate / evolution_enabled / snapshot_cleanup / cleanup_old_snapshots / count_cleanup / _tag_index / push_interval_minutes / runtime_state.json / heartbeat_timeout_s / read_file.original_size / tools/registry.run 流程契约）。
- `memory/manager.py::SCHEMA_VERSION = 58` 未 bump（已知遗留，5.9 是 DDL-only 二次回填，与 ADR-0017 D3 一致）。
- ADR-0019 全部 D1-D5 已落地（见 §三）。

## 五、变更范围

| 文件 | 改动 |
| --- | --- |
| `docs/adr/0020-architecture-v0-round-235-adr-0018-d1-d2-doc-landing.md`（new） | 本 ADR |
| `docs/architecture-v0.md` 顶部 ADR 索引行 20 | 措辞修正：从「commit `59387b4d`」→「commit `59387b4d`（仅 ADR 文本；doc 修复实际由本 ADR-0020 round 235 执行）」+ 追加本 ADR-0020 条目 |
| `docs/architecture-v0.md` §一 util/ 列表（行 52-54） | 7 → 8 modules，加 `print_guard.py` + 「v0.10 round 203 +print_guard，见 ADR-0018 / ADR-0020」 |
| `docs/architecture-v0.md` §二 util/ 子条目（行 131-132） | 7 → 8 modules，加 print_guard 注释行 |
| `docs/architecture-v0.md` §二 scoring/ 描述（行 137-139） | "持续仅 `__pycache__/`，缺 `__init__.py`" → "目录存在但完全空（含 `__pycache__/` 已无残留），未 git tracked；保留作为 v0.4 评分基线的占位，**不主动补 `__init__.py`**（与 ADR-0017 D1 决策一致；v0.13.1+ 二次清空实测，见 ADR-0017 / ADR-0018 / ADR-0020）" |
| `docs/architecture-v0.md` §四 scoring/ 不变量行（行 199） | 同上 |
| `docs/architecture-v0.md` §五版本对照表 v0.11+ (round 231) 行（行 225）之前插入 | 追加新行 v0.10 (round 203 + 215+ close-out)：「v0.10 (round 203 + 215+ close-out) \| `util/print_guard.py` 抽取（main.py `try/except Exception + print failed` 模板抽 helper；commit `605ed28e` round 203；tests/test_print_guard.py 14 cases 全过锁契约；**main.py 实际未接入 — 见 ADR-0018 D3 / ADR-0020 D3**）」 |

`src/xragent/main.py` 不动（D3 决策：留给后续 round 显式 turn）。
`src/xragent/tools/registry.py` docstring 不动（D4 决策：留给后续 round）。
`src/xragent/scoring/` 不动（D2 决策：不补 `__init__.py`、不建占位 .py）。
无 schema 变更、无行为变更、无测试破坏面。
