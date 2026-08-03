# ADR-0024: architecture-v0.md round 582+ drift scan + ADR-0020/0021/0022/0023 doc 修复**实际落地**

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-05
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。必须 write_file 改 docs/architecture-v0.md 或加 docs/adr/0001-*.md。改完 commit。"
- **范围**: 本轮独立扫描 `docs/architecture-v0.md` vs `src/xragent/` + `sandbox/` 实际树 + `git ls-files` + `git log --oneline`；一次性把所有未落地的 drift 全部 sync 到 doc。
- **前置**: ADR-0019 / ADR-0020 / ADR-0021 / ADR-0022 / **ADR-0023（同样描述了 10 处 drift 但本轮实测 doc 仍未修复——本 ADR-0024 是 ADR-0023 的实际落地轮）**

## 一、扫描方法

```
ls src/xragent/{util,memory,snapshot,scoring,tools}/
git ls-files src/xragent/ sandbox/
grep -n "5\.10\|5\.11\|v0\.4 \|v0\.10\b\|inspect\.py\|print_guard\|scoring\|SCHEMA_VERSION" docs/architecture-v0.md
wc -l src/xragent/memory/manager.py src/xragent/tools/registry.py
grep -n "print_guard" src/xragent/main.py
```

逐条对照 ADR-0023 D1–D10 + 新发现的 ADR-0024 D11–D13。

## 二、drift 清单（13 处，本轮全部 sync）

### D1 — §一 + §二 util/ 7 → 8，print_guard.py 漏列（ADR-0022 / 0023 主 drift #1）

- **doc 说**：§一 + §二均写 `7 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents`。
- **实际**：`ls src/xragent/util/` 8 个模块（新增 `print_guard.py` 61 行，commit `605ed28e` round 203 抽取，commit `a3c3d080` round 324 真接入 main.py，`main.py:24` `from .util.print_guard import print_guard` + `main.py:352/362/379` 实际使用）。
- **fix**：§一 + §二 util/ 子条目 7 → 8，加 print_guard 注释 + 引用 ADR-0018 / ADR-0020 / 本 ADR-0024。

### D2 — §一 memory schema 5.9 → 5.11 + SCHEMA_VERSION 注释（ADR-0022 / 0023 主 drift #3）

- **doc 说**：§一 schema 行写 5.9（5.0 + 5.1 + 5.3 + 5.4 + 5.5 + 5.6 + 5.7 + 5.8 + 5.9）+ "SCHEMA_VERSION = 58 未 bump 是已知遗留"。
- **实际**：`SCHEMA_VERSION = 511  # 5.11`（commit `cb13c186` "memory 5.10 → 5.11: +Fact.access_count + LFU recall"）；顶部注释列出 5.10（`expires_ts` + `idx_facts_expires_ts` partial + `set_expiry` / `recall_unexpired` / `purge_expired`）+ 5.11（`access_count` + `idx_facts_access_count_ts` + `recall_most_accessed` / `recall_least_accessed` / `increment_access_count`）。
- **fix**：§一 schema 行 5.9 → 5.11，追加 5.10 / 5.11 子项；§一 SCHEMA_VERSION 注释整段改 "SCHEMA_VERSION=511（5.11；与 `_migrate_all()` 实际跑到的最后一个版本同步，5.9 DDL-only 后又跨 5.10 / 5.11 两次 schema 演进）"；§二 memory/manager.py 行注释 305→317 → 1111 行；§五 v0.5 行去"未做 SCHEMA_VERSION bump" + 新增 5.10 TTL 行 + 5.11 LFU 行。

### D3 — §二 + §四 scoring/ 措辞："占位包 / 持续仅 __pycache__/" → v0.4 baseline 实现包（ADR-0022 / 0023 主 drift #2）

- **doc 说**（§二行 137-139 + §四行 199）："`scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；...v0.13.1 重新确认仍未建不删）"。
- **实际**（`ls src/xragent/scoring/` + `git ls-files`）：
  - `__init__.py` 1179 bytes（导出 `SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE` / `score_turn`），git tracked（commit `8125486d` round 425 "feat(scoring): v0.4 基线启发式 score_turn"）
  - `score.py` 7980 bytes / 200 行（4 公开 API：`_wall_ms_delta` / `_clip` / `_base_from_observation` / `score_turn` + 3 常量），git tracked（commit `a1d51ee2` refactor 抽出 `_base_from_observation`）
  - **main.py 当前未接入 score_turn**（ROADMAP v0.4 计划 "N 轮无 score 提升 → 自动进入长眠" 上层 wiring 留给后续 round）
- **fix**：§二 scoring/ 块名 + 注释全部重写；§四不变量行从 "scoring/ 目录占位" 改为 "scoring/ v0.4 baseline 实现" + 内容描述完整演进链；§五加 v0.4 行（commit `8125486d` + `a1d51ee2`）。

### D4 — §二 snapshot/ 漏列 `inspect.py`（ADR-0023 主 drift #4）

- **doc 说**（§二）：snapshot/ 下只列 `_tag_index.py` / `count_cleanup.py` / `age_cleanup.py` / `side_git.py`。
- **实际**（`ls src/xragent/snapshot/` + `git ls-files`）：`inspect.py` 8466 bytes / 226 行，git tracked（commit `467bf563` round 421 "autonomous: 加新功能小而具体" + tests +216 单测）；4 公开 API：`SnapshotMeta` dataclass / `_build_meta` / `list_snapshots_with_meta` / `count_over_age` / `format_snapshot_table`，属"读取 + 展示"层（cleanup 是写入层）。
- **fix**：§二 snapshot/ 子条目加 `inspect.py` 行；§五版本对照表加 v0.5.x snapshot/inspect.py 行（commit `467bf563`）。

### D5 — 顶部 ADR 索引停在 0019，漏 0020 / 0021 / 0022 / 0023（ADR-0023 主 drift #5 / D8）

- **doc 说**（行 19-20）：顶部只引用到 ADR-0019。
- **实际**（`ls docs/adr/`）：存在 `0020-architecture-v0-round-235-adr-0018-d1-d2-doc-landing.md` / `0021-architecture-v0-round-325-adr-0020-redo-and-scoring-truly-gone.md` / `0022-architecture-v0-round-405-doc-vs-code-drift-scan.md` / `0023-architecture-v0-round-562-drift-scan-and-adr-0022-landing.md` 4 个 ADR。
- **fix**：顶部索引追加 4 行 + 本 ADR-0024 行。

### D6 — §二 memory/ 漏列 `manager.py.bak.5.10` 留痕（**新发现，ADR-0024 D11**）

- **doc 说**（§二）：memory/ 下只列 `manager.py`。
- **实际**（`git ls-files src/xragent/memory/`）：`manager.py.bak.5.10` 38755 bytes，git tracked（5.10 → 5.11 migration 前的快照备份，与 `sandbox/manager_5_11_pre.py.bak` 45378 bytes 平行；后者也是 git tracked 但在 sandbox/ 下）。
- **fix**：§二 memory/ 子条目加 `manager.py.bak.5.10` 留痕行；不在 §一/§五版本表加单独行（备份留痕是 patch 流程的副作用，归 ADR-0019 / 本 ADR-0024 D6 一并管）。

### D7 — §二 tools/ 漏列 `evolve_tools.py.bak` 留痕（**新发现，ADR-0024 D12**）

- **doc 说**（§二）：tools/ 下只列 `evolve_tools.py`。
- **实际**（`git ls-files src/xragent/tools/`）：`evolve_tools.py.bak` 7844 bytes，git tracked（与 evolve_tools.py 同字节数，疑是 refactor 前的备份；具体 commit 待查）。
- **fix**：§二 tools/ 子条目加 `evolve_tools.py.bak` 留痕行。

### D8 — §二完全缺失 `sandbox/` 目录（**新发现，ADR-0024 D13**）

- **doc 说**（§二）：架构摘要完全不提 sandbox/ 目录。
- **实际**（`ls sandbox/` + `git ls-files sandbox/`）：18 文件 git tracked——脚本 `dream_new.py` / `hello.py` / `_patch_score_v1.py` / `patch_5_11.py` / `patch_evolve.py` + 备份 `manager_5_11_pre.py.bak` + 若干 `.probe*` canary。`patch_5_11.py` 留作 5.11→5.12 模板（diary round ~330）；`patch_evolve.py` 是 round 538 "改一处工具实现" 同期新增。
- **fix**：§二新增 `sandbox/` 块，说明它是 "patch 模板 + canary + 备份" 暂存区，git tracked 但不入 src/，HITL 工具白名单外。

### D9 — §一 tools/registry 行注释 317 → 318（**新发现，ADR-0024 minor**）

- **doc 说**（§一行 113）："v0.2.10 抽出 _safe_call helper，317 行，结构展开"。
- **实际**（`wc -l src/xragent/tools/registry.py`）：318 行。
- **fix**：317 → 318（一行差，不另开 ADR，归本 ADR-0024 一并修）。

### D10 — §一 main.py print_guard 接入状态（**新发现，ADR-0024 fact**）

- **doc 说**（顶部 ADR-0018 行 20）："v0.10 round 215+ close-out doc sync"。
- **实际**（`grep -n "print_guard" src/xragent/main.py`）：main.py:24 `from .util.print_guard import print_guard` + 行 352 / 362 / 379 实际 3 处调用。
- **fix**：§一 + §五 v0.10 行（新增）显式说明 main.py 已接入 print_guard（commit `a3c3d080` round 324），不写"未接入"措辞（与 ADR-0023 D10 同步）。

### D11 — §四不变量 scoring/ 行完全未在 doc 反映（**新发现，ADR-0024**）

- **doc 说**（§四不变量行）："scoring/ 目录占位" —— v0.13.1 措辞。
- **实际**：见 D3。
- **fix**：§四不变量 scoring/ 行整段重写。

### D12 — §五版本对照表缺 v0.4 / v0.10 / 5.10 / 5.11 / snapshot-inspect 行（**新发现，ADR-0024**）

- **doc 说**（§五版本对照表）：从 v0.5.9 → v0.11 → v0.11+ (round 231) 连续，**缺**：
  - v0.4 (scoring v0.4 baseline round 425)
  - v0.10 (print_guard 抽取 round 203 + 接入 round 324)
  - v0.5.x (5.10 TTL round ~327)
  - v0.5.x (5.11 LFU round ~340，commit `cb13c186`)
  - v0.5.x (snapshot/inspect.py round 421，commit `467bf563`)
- **fix**：§五版本对照表在 v0.5.9 行（v0.5.x block 末尾）→ v0.11 行（round 425 块）之间插入 v0.4 / v0.10 / 5.10 / 5.11 / snapshot-inspect 5 行。

### D13 — §一 util/ 注释 heartbeat / http_parents 注释尾未追加 v0.10 print_guard（ADR-0023 D9）

- **doc 说**（§一）："v0.2.7 +heartbeat，见 ADR-0008；v0.2.8 +http_parents，见 ADR-0009" —— 未提及 v0.10。
- **fix**：注释尾追加 "v0.10 round 203 +print_guard（见 ADR-0018 / ADR-0020）"。

## 三、变更范围表（实际执行）

| # | 改动 | 锚点 |
| --- | --- | --- |
| 1 | 顶部 ADR 索引追加 0020 / 0021 / 0022 / 0023 / 0024 五行 | 在 `[ADR-0019]` 行后追加 |
| 2 | §一 util/ 7 → 8，加 print_guard.py + v0.10 注释 | `当前 **7 个模块**：` → `当前 **8 个模块**：` + http_parents 后追加 print_guard |
| 3 | §一 memory schema 5.9 → 5.11 + SCHEMA_VERSION 注释 | `当前有效 schema **5.9**` → `当前有效 schema **5.11**` + 追加 5.10 / 5.11 子项 + 重写 SCHEMA_VERSION 注释 |
| 4 | §一 tools/registry 行注释 317 → 318 | `317 行` → `318 行` |
| 5 | §一 util/ 注释尾追加 v0.10 print_guard hint | heartbeat / http_parents 注释后追加 |
| 6 | §二 util/ 7 → 8 模块清单 | `# 7 个模块：json_utils` → `# 8 个模块：json_utils ... / print_guard` |
| 7 | §二 memory/manager.py 注释 305→317 → 1111 行 + 5.10/5.11 子项 + 加 manager.py.bak.5.10 留痕 | `schema 5.9（v0.2.7 +LRU 5.8；...）` → `schema 5.11（v0.2.7 +LRU 5.8；...v0.5.x +5.10 TTL；v0.5.x +5.11 LFU；... 1111 行）` + 子条目追加 bak |
| 8 | §二 snapshot/ 加 inspect.py | 在 `_tag_index.py` 后追加 `inspect.py` |
| 9 | §二 scoring/ 占位包 → v0.4 baseline 实现包 | `scoring/                   # 占位包（v0.13.1 状态：持续仅 __pycache__/，缺 __init__.py，未 git tracked；...` → `scoring/                   # v0.4 baseline 实现包（round 425 commit 8125486d + round 425 refactor a1d51ee2；__init__.py 1179b + score.py 7980b / 200 行；导出 score_turn + 3 常量；git tracked；main.py 尚未接入 — ROADMAP v0.4 长眠判定 wiring 留给后续 round）` |
| 10 | §二 tools/ 加 evolve_tools.py.bak 留痕 | 在 `evolve_tools.py      # propose_self_replace / terminate（高危，HITL 门控）` 后追加 `evolve_tools.py.bak  # refactor 前备份（git tracked，7844b，待清理决策）` |
| 11 | §二尾部加 sandbox/ 块 | 在 `llm/` 行后追加 `sandbox/  # 暂存区：patch 模板 (patch_5_11.py / patch_evolve.py / _patch_score_v1.py) + 备份 (manager_5_11_pre.py.bak) + .probe* canary + dream_new.py / hello.py；git tracked 18 文件；不在 src/，HITL 工具白名单外` |
| 12 | §四不变量 scoring/ 行整段重写 | `\| scoring/ 目录占位 \| ...` → `\| scoring/ v0.4 baseline 实现 \| ...` |
| 13 | §五版本对照表加 v0.4 / v0.10 / 5.10 / 5.11 / snapshot-inspect 5 行 | 在 v0.5.9 行后插入 |

## 四、本 ADR 自我约束

- 不触碰 src/ 任何 .py（除 archive 留痕文件 `.bak` 在 git tracked 内不动）。
- 不重写 ADR-0017 / ADR-0018 / ADR-0019 / ADR-0020 / ADR-0021 / ADR-0022 / ADR-0023 已存在内容；仅在 architecture-v0.md 落地它们提出的 doc 修复方案。
- commit message 写明 "ADR-0024 实际落地 ADR-0020/0021/0022/0023 所有未生效的 doc 修复"，让 supervisor 后续 close-out 知道本轮是 close-out chain 的真正收口。
- 一次性原子 commit（ADR 文本 + architecture-v0.md 改动 + diary 留痕），避免 supervisor autonomous reset 抹掉任一部分。

## 五、commit 计划

```
git add docs/adr/0024-architecture-v0-round-582-actual-doc-landing.md
git add docs/architecture-v0.md
git commit -m "docs(arch): ADR-0024 + sync architecture-v0.md (round 582+ drift fix, 13 处)

D1 §一 §二 util/ 7→8 + print_guard.py 注释（main.py:24 已接入, round 324 commit a3c3d080）
D2 §一 memory schema 5.9→5.11 (commit cb13c186) + SCHEMA_VERSION=511 注释 + §二行数 1111
D3 §二 §四 scoring/ 占位包→v0.4 baseline 实现 (commit 8125486d + a1d51ee2)
D4 §二 snapshot/ 加 inspect.py (commit 467bf563)
D5 顶部 ADR 索引补 0020/0021/0022/0023/0024
D6 §二 memory/ 加 manager.py.bak.5.10 留痕
D7 §二 tools/ 加 evolve_tools.py.bak 留痕
D8 §二 新增 sandbox/ 块
D9 §一 tools/registry 行注释 317→318
D10 §一 §五 v0.10 行显式说明 main.py print_guard 已接入
D11 §四不变量 scoring/ 行整段重写
D12 §五版本对照表加 v0.4/v0.10/5.10/5.11/snapshot-inspect 5 行
D13 §一 util/ 注释尾追加 v0.10 print_guard hint

13 处 drift 全部 sync，commit cb13c186 / 8125486d / a1d51ee2 / 467bf563 / 605ed28e /
a3c3d080 全部反映到 doc。"
```
