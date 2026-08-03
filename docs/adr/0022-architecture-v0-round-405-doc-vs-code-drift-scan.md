# ADR-0022: architecture-v0.md round 405+ drift 扫描 — 10 处 code-vs-doc 失真修复方案 + ADR-0018/0020/0021 错误前提更正

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-04
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步；本次扫到的所有 drift 在本 ADR 一并 fix。
- **前置**: ADR-0017 / 0018 / 0019 / 0020 / 0021

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树（`ls src/xragent/{util,memory,snapshot,scoring}/`）+ `git log --oneline` 实际 commit hash，核对：

1. `src/xragent/util/` 文件清单 vs doc §一 / §二 util/ 子条目（7 vs 实际 8）。
2. `src/xragent/scoring/` 当前空状态 vs doc §二 / §四 scoring/ 描述（v0.13.1 旧表述 vs 实际"目录彻底空"）。
3. `main.py` print_guard 接入 vs ADR-0018 D3 / ADR-0020 D3 假设的"未接入"。
4. `memory/manager.py` SCHEMA_VERSION vs §一 memory schema 行 + §五 v0.5 行"已知遗留 SCHEMA_VERSION 未 bump"。
5. §五版本对照表是否覆盖 round 203 print_guard 抽取、round 324 print_guard 接入、round 327+ 5.10 TTL、round 325+ scoring/ 二次清空。
6. 顶部 ADR 索引是否引用 ADR-0020 / ADR-0021。

## 二、drift 清单

### D1 — `util/print_guard.py` 漏列（§一 + §二双处失真，**主 drift #1**）

- **doc 说**（§一行 52 / §二行 131）：
  > 当前 **7 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` /
  > `diary_archive` / `git_helpers` / `heartbeat` / `http_parents`
  > （v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；
  > v0.2.8 +http_parents，见 ADR-0009）
- **实际**（`ls src/xragent/util/`）：**8 个模块**，含 `print_guard.py`（commit `605ed28e` round 203 抽 helper，commit `a3c3d080` round 324 真接入 main.py）。
- **fix**：§一 + §二 7 → 8，`print_guard.py` 加在 http_parents 之后；§一 util/ 注释追加 "v0.10 round 203 +print_guard（见 ADR-0018）"。

### D2 — `scoring/` 目录彻底空，但 §二 / §四仍写 v0.13.1 "持续仅 __pycache__/"（**主 drift #2**）

- **doc 说**（§二行 137-139 + §四行 199）：
  > `scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；...）
- **实际**（`find src/xragent/scoring -mindepth 1 | wc -l`）：`0` —— 目录彻底空，连 `__pycache__/` 都没了（ADR-0021 round 325+ 确认）。
- **fix**：§二 + §四 scoring/ 措辞改"目录本身存在但完全空（v0.13.1 状态；round 325+ ADR-0021 进一步确认无 `__pycache__/`）"。

### D3 — §一 memory schema 写 5.9，但代码 SCHEMA_VERSION=510（**主 drift #3**）

- **doc 说**（§一行 47）：
  > `memory/manager.py` 当前有效 schema **5.9**（5.0 基线 + 5.1 `source_turn_idx` + ... + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建）
- **实际**（`grep SCHEMA_VERSION src/xragent/memory/manager.py`）：`SCHEMA_VERSION = 510  # 5.10`（commit `559b04c7` feat(memory) 5.10 TTL 已 push）。
- **fix**：§一 schema 列表追加 "5.10 `expires_ts` + `idx_facts_expires_ts` partial + `set_expiry` / `recall_unexpired` / `purge_expired`"；SCHEMA_VERSION 注释去掉"未 bump"措辞。

### D4 — §五 v0.5 行"已知遗留 SCHEMA_VERSION 未 bump"已过时

- **doc 说**（§五行 257）：
  > 未做：`SCHEMA_VERSION` 常量 bump（已知遗留，5.9 是 DDL-only 二次回填不增字段）
- **实际**：5.10 commit `559b04c7` 已 bump 到 510；不是"不增字段"理由（5.10 增了 `expires_ts` 字段）。
- **fix**：§五 v0.5 行去"未做"条目；5.10 不变量另立。

### D5 — §五版本对照表缺 v0.10 行（round 203 + round 324 print_guard）

- **doc 说**：§五只到 v0.11+ round 231，无 v0.10 条目。
- **实际**：commit `605ed28e`（round 203 抽 `util/print_guard.py` + 14 测试用例）+ commit `a3c3d080`（round 324 main.py 接入 3 处重复 try/except）。
- **fix**：§五加 v0.10 行，覆盖"print_guard helper 抽取（round 203, commit `605ed28e`）+ main.py 真接入（round 324, commit `a3c3d080`，3 处 push/task gen/commit try/except 包到 print_guard helper）"。

### D6 — §五版本对照表缺 v0.13 行（scoring/ 二次清空）

- **doc 说**：§五无 v0.13 条目。
- **实际**：round 325+ ADR-0021 确认 scoring/ 目录彻底空（连 __pycache__/ 都没）。
- **fix**：§五加 v0.13 行，覆盖"scoring/ 二次清空（round 325+, ADR-0021；目录本身存在但完全空）"。

### D7 — §五版本对照表缺 5.10 TTL 行（round 327+）

- **doc 说**：§五 v0.5 行只到 5.9 schema；§五末尾 v0.11+ 只到 age_cleanup。
- **实际**：commit `559b04c7` feat(memory) 5.10 TTL 已 ship；`expiry` 工具尚未注册到 registry（缺 `memory_set_expiry` / `memory_recall_unexpired` / `memory_purge_expired` 工具暴露，待后续 round 决策）。
- **fix**：§五加 5.10 TTL 行，覆盖"`memory/manager.py` +expires_ts + idx_facts_expires_ts partial + 3 方法（set_expiry / recall_unexpired / purge_expired）；commit `559b04c7`；SCHEMA_VERSION 510；47 passed in 2.90s"。

### D8 — 顶部 ADR 索引缺 ADR-0020 / ADR-0021 行

- **doc 说**（行 19-20）：索引只到 ADR-0019。
- **实际**：`docs/adr/0020-...md` + `0021-...md` 都存在但顶部未引用。
- **fix**：行 19 追加 ADR-0020 + ADR-0021 索引行。

### D9 — §一 util/ 注释漏 v0.10 round 203 +print_guard

- **doc 说**（§一行 60）：
  > v0.1.1 +diary_archive/git_helpers；v0.2.7 +heartbeat，见 ADR-0008；
  > v0.2.8 +http_parents，见 ADR-0009
- **fix**：注释尾追加 "；v0.10 round 203 +print_guard，见 ADR-0018（round 324 main.py 真接入，见 ADR-0022 D5）"。

### D10 — ADR-0018 D3 / ADR-0020 D3 "main.py 未接入 print_guard"前提已打破

- **doc 说**（ADR-0018 D3 / ADR-0020 D3 段落）："main.py 实际未接入 print_guard"。
- **实际**：commit `a3c3d080`（round 324 "autonomous: 用 print_guard 包 3 处重复 try/except"）已将 3 处（push / task gen / commit）包到 `print_guard(...)` helper；main.py 第 24 行 `from .util.print_guard import print_guard` + 第 352 / 362 / 379 行 3 处调用；tests/test_print_guard.py 14 cases 锁契约。
- **fix**：本 ADR 记录 fact；不动 ADR-0018 / ADR-0020 文字（保留历史 trail），但 §一 util/ 注释 + §五 v0.10 行显式说明 "main.py 真接入"。

## 三、修复范围与顺序

按"由小到大、不破坏 §三 §四 §五 表结构"原则，分 5 处 str.replace 精确锚点替换：

1. 顶部 ADR 索引追加 ADR-0020 + ADR-0021 行（D8）。
2. §一 util/ 行 52 "7 个模块" → "8 个模块" + print_guard.py（D1） + 行 60 注释追加（D9）。
3. §一 memory schema 行 47 "5.9" → "5.10" + 5.10 子项追加（D3）。
4. §二行 131 util/ "7 个模块" → "8 个模块"（D1）；§二行 137-139 scoring/ 措辞改"目录本身存在但完全空"（D2）；§四行 199 scoring/ 同改（D2）。
5. §五 v0.5 行去"未做 SCHEMA_VERSION bump"条目（D4）；§五末尾追加 v0.10 / v0.13 / 5.10 TTL 3 行（D5 / D6 / D7）。

## 四、不在本轮范围

- `memory_set_expiry` / `memory_recall_unexpired` / `memory_purge_expired` 工具暴露（tools/memory_tools.py + tools/registry.py）：5.10 TTL 已有内部方法，未注册到 registry 工具面；决策留给后续 round。
- `memory/manager.py.bak` 删除（ADR-0013 D8 已回溯 `git rm`）：本轮无变化。
- `__tools_probe__.txt` 清理（ADR-0011 D3）：本轮无变化。

## 五、commit 计划

`docs(arch): ADR-0022 + sync architecture-v0.md (round 405+ drift fix, 10 处)` —— 包含 ADR-0022 新文件 + architecture-v0.md 5 处 str.replace 精确替换 + diary/2026-08-04.md 段落。