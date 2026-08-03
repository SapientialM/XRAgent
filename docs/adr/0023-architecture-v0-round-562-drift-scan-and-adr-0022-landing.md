# ADR-0023: architecture-v0.md round 562 drift 扫描 — ADR-0022 实际落地 + 5.10/5.11 schema + v0.4 scoring baseline + snapshot/inspect + v0.10 print_guard 二次入表

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-03
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步；本轮一次性 fix ADR-0022 设计但从未实际落地的 D1/D3/D4/D5/D7/D8/D9/D10 + 5.11 LFU + v0.4 scoring baseline + snapshot/inspect 漏列 + 顶部 ADR 索引 0020/0021/0022 补齐
- **前置**: ADR-0017 / 0018 / 0019 / 0020 / 0021 / 0022

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树（`ls src/xragent/{util,memory,snapshot,scoring}/`）+ `git log --oneline` 实际 commit hash，核对：

1. ADR-0022 D1-D10 是否实际应用（"Accepted" 但 §五 commit 计划"docs(arch): ADR-0022 + sync architecture-v0.md ..."从未出现在 git log 里）。
2. `src/xragent/scoring/` 是否仍为空（ADR-0022 D2 假设"目录彻底空"）。
3. `src/xragent/memory/manager.py::SCHEMA_VERSION` 当前值（ADR-0022 D3 假设 5.10）。
4. `src/xragent/snapshot/` 是否新增 `inspect.py`（commit `467bf563` round 421）。
5. `src/xragent/util/` 模块数（ADR-0022 D1 假设 8）。
6. 顶部 ADR 索引是否引用 ADR-0020 / 0021 / 0022（ADR-0022 D8）。
7. §五版本对照表是否覆盖 v0.4 scoring / v0.10 print_guard / 5.10 TTL / 5.11 LFU / snapshot inspect。

## 二、drift 清单

### D1 — ADR-0022 D1/D3/D4/D5/D7/D8/D9/D10 全部未落地（**主 drift #1**）

- **doc 说**：ADR-0022 §三"5 处 str.replace 精确锚点替换" + §五 commit 计划 `docs(arch): ADR-0022 + sync architecture-v0.md (round 405+ drift fix, 10 处)`。
- **实际**：`git log --oneline -- docs/architecture-v0.md` 无任何 "ADR-0022" / "round 405+" / "drift fix" 提交；architecture-v0.md 顶部 ADR 索引仍停在 ADR-0019；§一 util/ 仍写 "7 个模块"；§一 memory schema 仍写 "5.9" + "SCHEMA_VERSION=58 未 bump 是已知遗留"；§五 v0.5 行仍写"未做：SCHEMA_VERSION 常量 bump"。
- **fix**：本 ADR-0023 一次性完成 ADR-0022 D1（§一 §二 util/ 7→8 + print_guard）/ D3（§一 §二 §四 schema 5.10 → 5.11）/ D4（§五 v0.5 行去"未做 SCHEMA_VERSION bump"）/ D5（§五 v0.10 print_guard 行）/ D7（§五 5.10 TTL 行 + 5.11 LFU 行）/ D8（顶部 ADR 索引补 0020/0021/0022）/ D9（§一 util/ 注释尾追加 v0.10 print_guard）/ D10（§一 util/ 注释 + §五 v0.10 行显式说明 main.py 真接入 print_guard）。

### D2 — `scoring/` 已实现 v0.4 baseline，但 §二 / §四仍写"占位 / 持续仅 __pycache__/"（**主 drift #2**）

- **doc 说**（§二 + §四）：
  > `scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；...v0.13.1 重新确认仍未建不删）
- **实际**（`ls src/xragent/scoring/` + `git ls-files src/xragent/scoring/`）：
  - `__init__.py` 1179 bytes（导出 `SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE` / `score_turn`）
  - `score.py` 7980 bytes（4 公开 API：`_wall_ms_delta` / `_clip` / `_base_from_observation` / `score_turn` + `SCORE_OK_BASE=0.7` / `SCORE_ERROR=0.0` / `SCORE_RANGE=(0.0, 1.0)` 三个常量 + 模块 docstring 写明 "ROADMAP v0.4 第一步只需要'一个可解释的启发式'"）
  - 都 git tracked（commit `8125486d` "feat(scoring): v0.4 基线启发式 score_turn (round 425)" + commit `a1d51ee2` "refactor(scoring): 抽 _base_from_observation helper + 简化 wall_ms 插值"）
  - **ROADMAP.md v0.4 行仍写"（计划）"** —— 这是 ROADMAP 自身 drift，本 ADR 仅记 fact，不动 ROADMAP（ROADMAP 同步留给父母 turn 决策）
- **fix**：§二 + §四 scoring/ 措辞全段重写为"v0.4 baseline 实现包（round 425+ commit `8125486d` + commit `a1d51ee2` refactor；`score.py` + `__init__.py` 均 git tracked；导出 `score_turn(record) -> float` 纯函数 + 3 评分常量；不修改 TurnRecord、不引 LLM、不 IO；上层 watchdog / 长眠判定自行决定调用时机）"；§五加 v0.4 行。

### D3 — §一 memory schema 写 5.9，§五 v0.5 行写"SCHEMA_VERSION 未 bump 是已知遗留"，实际已 5.11（**主 drift #3**）

- **doc 说**（§一行 47 + §五行 257）：
  > `memory/manager.py` 当前有效 schema **5.9**（... 5.8 `last_accessed_ts` LRU + 5.9 `idx_facts_title` 重建 + 5.4 `idx_facts_tags` 重建），...
  > 未做：`SCHEMA_VERSION` 常量 bump（已知遗留，5.9 migration 是 DDL-only 的二次回填，不改字段）
- **实际**（`grep SCHEMA_VERSION src/xragent/memory/manager.py` + `git log -- src/xragent/memory/manager.py`）：
  - `SCHEMA_VERSION = 511  # 5.11`（commit `cb13c186` "memory 5.10 → 5.11: +Fact.access_count + LFU recall"）
  - 顶部注释列出 5.10 (`expires_ts` + `idx_facts_expires_ts` partial + `set_expiry` / `recall_unexpired` / `purge_expired`) + 5.11 (`access_count` + `idx_facts_access_count_ts` + `recall_most_accessed` / `recall_least_accessed` / `increment_access_count`)
  - Fact dataclass 行 56 `access_count: int = 0  # 5.11: 访问次数, 与 last_accessed_ts 配合做精确 LFU`
  - `_migrate_all()` 链 11 步：5.1 / 5.3 / 5.4 / 5.5 / 5.6 / 5.7 / 5.8 / 5.9 / 5.10 / 5.11
  - 总行数 1111
- **fix**：§一 schema 行 5.9 → 5.11，追加 5.10 / 5.11 子项；§一 SCHEMA_VERSION 注释整段去掉"未 bump"措辞，改为"SCHEMA_VERSION=511（5.11；与 `_migrate_all()` 实际跑到的最后一个版本同步）"；§二 memory/manager.py 注释追加"v0.5.x +5.10 TTL（commit `559b04c7`）+ v0.5.x +5.11 LFU（commit `cb13c186`），1111 行"；§五 v0.5 行去"未做 SCHEMA_VERSION bump" + 新增 5.10 TTL 行 + 5.11 LFU 行。

### D4 — §二 `snapshot/` 漏列 `inspect.py`（**主 drift #4**）

- **doc 说**（§二）：snapshot/ 下只列 `_tag_index.py` / `count_cleanup.py` / `age_cleanup.py` / `side_git.py`。
- **实际**（`ls src/xragent/snapshot/` + `git log -- src/xragent/snapshot/inspect.py`）：
  - `inspect.py` 8466 bytes，git tracked（commit `467bf563` round 421 "autonomous: 加新功能小而具体" + tests +216 单测）
  - 4 公开 API：`SnapshotMeta` dataclass / `_build_meta` / `list_snapshots_with_meta` / `count_over_age` / `format_snapshot_table`
  - 与 `_tag_index` / `age_cleanup` / `count_cleanup` 平级，属"读取 + 展示"层（cleanup 是写入层）
- **fix**：§二 snapshot/ 子条目加 `inspect.py` 行；§五版本对照表加 "v0.5.x snapshot/inspect.py" 行（commit `467bf563`，与 `count_over_age` / `format_snapshot_table` 等 4 API 一并 ship）。

### D5 — §三工具数 19 个仍正确（5.10 / 5.11 内部方法未注册工具面，**未变不变量**）

- **doc 说**：§三 + §四 "工具总数 19 个" + §二 memory_tools "7 个 memory_* 工具"。
- **实际**（`grep "add(\"" src/xragent/tools/registry.py`）：19 个 `add(...)` 调用，read_file / list_dir / write_file / run_cmd / git_commit / git_push / snapshot_cleanup / memory_save / memory_recall / memory_recall_range / memory_top_frequent / memory_recall_by_tag / memory_recall_by_title / memory_update_title / diary_write / propose_self_replace / curl_url / web_search / terminate = 19；无 `memory_set_expiry` / `memory_recall_unexpired` / `memory_purge_expired` / `memory_recall_most_accessed` / `memory_recall_least_accessed` 工具暴露。
- **fix**：本 ADR 记 fact；§三 / §四 不变；§五 5.10 / 5.11 行显式说明"内部方法未注册工具面，决策留给后续 round"。

### D6 — 顶部 ADR 索引缺 ADR-0020 / 0021 / 0022 行（**主 drift #5**）

- **doc 说**（顶部行 19）：索引只到 ADR-0019。
- **实际**（`ls docs/adr/`）：`0020-architecture-v0-round-235-adr-0018-d1-d2-doc-landing.md` + `0021-architecture-v0-round-325-adr-0020-redo-and-scoring-truly-gone.md` + `0022-architecture-v0-round-405-doc-vs-code-drift-scan.md` 都已存在。
- **fix**：顶部 ADR 索引行 19 追加 3 行（ADR-0020 / 0021 / 0022 + 本 ADR-0023 一并追加 4 行）。

### D7 — `main.py.bak` + `tools/evolve_tools.py.bak` 留痕（**留痕类，非语义 drift**）

- **doc 说**：ADR-0013 D8 提 `memory/manager.py.bak` 已 `git rm` 删除；§二无 `.bak` 留痕条目；§四不变量未提 `.bak`。
- **实际**（`ls src/xragent/*.bak src/xragent/tools/*.bak`）：
  - `src/xragent/main.py.bak` 17935 bytes（未 git tracked，git ls-files 不列）
  - `src/xragent/tools/evolve_tools.py.bak` 7844 bytes（未 git tracked）
  - 都是本地备份残留（与 commit `07992253` "fix(deadlock): 修复 31 轮 close-out↔revert 死循环 + 实装父母 TUI/metamorphose 任务" 同期附近的 src/ 重构留下的临时备份）
- **fix**：§四不变量新增一行 `.bak 留痕` 不变量（`main.py.bak` / `evolve_tools.py.bak` 为本地重构临时备份，未 git tracked，未参与运行时；cleanup 决策留给父母 turn）；本 ADR 记 fact。

### D8 — §二 `tools/registry.py` 行数 317 → 318（**行数微差**）

- **doc 说**（§二行 88-89）："（v0.2.10 抽出 _safe_call helper，317 行，结构展开）"。
- **实际**（`wc -l src/xragent/tools/registry.py`）：318 行（v0.5.x 5.11 schema 同步期 +1）。
- **fix**：§二 tools/registry.py 注释 317 → 318；本 ADR 记 fact。

## 三、修复范围与顺序

按"由小到大、不破坏 §三 §四 §五 表结构"原则，分 6 处 str.replace 精确锚点替换：

1. 顶部 ADR 索引追加 ADR-0020 + ADR-0021 + ADR-0022 + ADR-0023 共 4 行（D6）。
2. §一 util/ 行 52 "7 个模块" → "8 个模块" + print_guard.py（D1/D2 二次落地）+ 行 60 注释追加 v0.10 print_guard（D9 / D10）。
3. §一 memory schema 行 47 "5.9" → "5.11" + 5.10 / 5.11 子项追加 + SCHEMA_VERSION 注释去"未 bump"措辞（D3）。
4. §二 util/ "7 个模块" → "8 个模块"（D1）；§二 snapshot/ 加 inspect.py（D4）；§二 scoring/ 措辞改 v0.4 baseline 实现（D2）；§二 tools/registry.py 行数 317 → 318（D8）；§二 memory/manager.py 注释追加 5.10/5.11 + 行数（D3）。
5. §四 scoring/ 措辞改 v0.4 baseline 实现（D2）；§四不变量加 `.bak 留痕` 行（D7）。
6. §五 v0.5 行去"未做 SCHEMA_VERSION bump" + §五末尾追加 v0.4 / 5.10 TTL / 5.11 LFU / v0.10 print_guard / snapshot inspect 共 5 行（D2/D3/D5）。

## 四、不在本轮范围

- `memory_set_expiry` / `memory_recall_unexpired` / `memory_purge_expired` / `memory_recall_most_accessed` / `memory_recall_least_accessed` 工具暴露（tools/memory_tools.py + tools/registry.py）：5.10 TTL + 5.11 LFU 已有内部方法，未注册到 registry 工具面；决策留给后续 round。
- `main.py.bak` / `evolve_tools.py.bak` cleanup：本轮仅留痕（§四不变量新增 `.bak 留痕` 行），不主动 `rm`；cleanup 决策留给父母 turn。
- `__tools_probe__.txt` 清理（ADR-0011 D3）：本轮无变化。
- ROADMAP.md v0.4 行"（计划）"措辞：与 architecture-v0 同步口径冲突，本轮仅记 fact 不改 ROADMAP。
- `memory/manager.py.bak` 删除（ADR-0013 D8 已回溯 `git rm`）：本轮无变化（早已清理）。

## 五、commit 计划

`docs(arch): ADR-0023 + sync architecture-v0.md (round 562 drift fix, ADR-0022 实际落地 + 5.10/5.11 + v0.4 scoring + snapshot/inspect + .bak 留痕)` —— 包含 ADR-0023 新文件 + architecture-v0.md 6 处 str.replace 精确替换 + diary/2026-08-03.md 段落留痕。