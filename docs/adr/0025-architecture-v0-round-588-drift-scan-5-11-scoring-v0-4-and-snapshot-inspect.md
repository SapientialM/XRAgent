# ADR-0025: architecture-v0.md round 588 drift 扫描 — schema 5.11 + scoring v0.4 baseline + snapshot/inspect 全部漂移

- **状态**: 已落地（仅 doc 同步，未碰 src/）
- **时间**: round 588 drift 扫描
- **触发**: 父母指令「读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失」
- **前置 ADR**: ADR-0017（v0.13.1 doc-vs-code drift） / ADR-0022（round 405） / ADR-0023（round 562） /
  ADR-0024（round 582 实际落地）
- **本 ADR 落地 commit**: 同 commit chain

## 一、问题陈述

round 562 后（ADR-0023）文档承诺要做「5.10/5.11 schema + v0.4 scoring baseline + snapshot/inspect +
v0.10 print_guard 二次入表」（见 ADR-0023 标题与 §三清单），但 round 582 ADR-0024 落地时只
覆盖了 §一 §三 §四 §五 的 web_search 限流 + autonomous journal + rng 显式参数化增量，**没把
ADR-0023 清单里的 4 项做到 §五版本对照表**。本轮按父母指令做一次 code-vs-doc drift 扫描，确认
src/ 实际进度远超文档描述。

## 二、Drift 清单（10 项）

### Drift A — 严重（代码 ≠ 文档，会误导后续 round）

**A1. memory schema 「5.9」 过期为 5.11**

- 文档 §一 + §四 + §五都写「当前有效 schema 5.9」「`SCHEMA_VERSION = 58` 未 bump 是已知遗留」
- 实际 `src/xragent/memory/manager.py`:
  - line 36: `SCHEMA_VERSION = 511  # 5.11`
  - line 338-339: `_migrate_v510()` + `_migrate_v511()` 都跑了
  - line 491-510: `_migrate_v511()` 真实存在并做 DDL
- 5.10 增量（v0.5.10 落地）：
  - facts +`expires_ts`（TTL 用）+ 索引
  - 新增 `recall_unexpired()` / `purge_expired()` / `set_ttl()`
- 5.11 增量（v0.5.11 落地）：
  - `Fact.access_count: int = 0`（line 56）
  - facts +`access_count INTEGER NOT NULL DEFAULT 0`（line 86）
  - `idx_facts_access_count_ts` 索引（line 111-113）
  - 3 方法：`recall_most_accessed`（line 1003）/ `recall_least_accessed`（line 1038）/
    `increment_access_count`（line 1072）
- 文档 line 16 "有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准" —— 口径写对了但版本号错了

**A2. §一 §二 §四 scoring/ 「占位」描述完全过时**

- 文档 §二 line 152 + §四 line 214 + ADR-0017 / ADR-0022 / ADR-0023 都反复强调
  「v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked; cleanup 决策留给后续轮次」
- 实际：
  - `src/xragent/scoring/__init__.py` 827 bytes（git tracked，`from .score import SCORE_ERROR, SCORE_OK_BASE, SCORE_RANGE, score_turn`）
  - `src/xragent/scoring/score.py` 7980 bytes（git tracked，含完整启发式实现）
  - commit `8125486d feat(scoring): v0.4 基线启发式 score_turn (round 425)`
  - commit `a1d51ee2 refactor(scoring): 抽 _base_from_observation helper + 简化 wall_ms 插值`
- ROADMAP v0.4 节明确「每个 turn 加 score 字段（默认 None；测试通过率作为基线）」 —— 已 ship

**A3. §五版本对照表缺 5 个版本 entry**

文档 §五版本表最后一条停在 v0.13.2（round 582），但实际已落地的版本没写入：

| 缺记版本 | 关键事件 | commit |
| --- | --- | --- |
| v0.4 | scoring/ v0.4 基线（启发式 score_turn） | `8125486d` |
| v0.5.10 | memory schema 5.10: facts +`expires_ts` + TTL 索引 + 3 方法 | `cb13c186` 父链 |
| v0.5.11 | memory schema 5.11: facts +`access_count` + `idx_facts_access_count_ts` + 3 LFU 方法，`SCHEMA_VERSION` bump 58 → 511 | `cb13c186` |
| v0.10 (round 215+) | `util/print_guard.py` 抽取（main.py `cmd_autonomous` 3 处 `try/except + print failed` 模板） | `59387b4d` 链 |
| v0.5.x (round 421) | `snapshot/inspect.py` 新增 | `467bf563` |

### Drift B — 中等（模块清单缺描述）

**B1. §二模块清单缺 `snapshot/inspect.py`**

- 实际：`src/xragent/snapshot/inspect.py` 8466 bytes（git tracked, commit `467bf563` round 421）
- §二 snapshot/ 段只列了 `__init__.py` / `_tag_index.py` / `age_cleanup.py` / `count_cleanup.py` / `side_git.py` —— 漏 inspect
- 推测功能：snapshot tag 检视（不属于清理路径，与 `_tag_index` 共享原语可能性高）

**B2. §二 §四 scoring/ 描述 vs 代码冲突**

- §二 line 152 写「占位包...持续仅 `__pycache__/`」
- §四 line 214 写同样描述
- 与 A2 重复，落地时一并改

### Drift C — 较小（untracked/tracked 残留未提）

**C1. `src/xragent/main.py.bak` (untracked, 17935 bytes, 444 行)**

- `wc -l`: main.py 451 行 vs main.py.bak 444 行，`diff -q` 报「Files differ」
- `git log -- src/xragent/main.py.bak` 完全空 —— untracked，不是 commit 残留
- §二模块清单 §四不变量表都没提此文件
- 推测来源：手动备份 / sed edit 残留 / 早期 refactor 备份
- 决策：本 ADR 不删（不属于 src/ 改动），留待后续 round 显式 HITL 决定 `rm` 或 `git add`

**C2. `src/xragent/memory/manager.py.bak.5.10` (tracked, 38755 bytes)**

- git tracked，commit `cb13c186 memory 5.10 → 5.11` 同期
- ADR-0011 / ADR-0013 D8 说「`memory/manager.py.bak` 留痕 → CM commit `cecfef33` `git rm` 主动清理」 —— 是 `manager.py.bak`（无后缀）已删
- 但 `manager.py.bak.5.10` 是迁移前的版本快照，命名带 `.5.10` 暗示是 5.10 → 5.11 升级前的留底，**与 ADR-0013 删的 `.bak` 不同文件**
- §二 / §四不变量表未提此 `.bak.5.10` —— 应显式登记「5.10 → 5.11 迁移前的版本快照，git tracked 不删，清理决策留给后续 round」

## 三、决策

**D1. 仅 doc 同步，不碰 src/**

- 本 ADR 与 ADR-0022 / 0023 / 0024 一致：drift 扫描的目的是修正文档而非回滚代码
- 5.11 schema / v0.4 scoring / snapshot/inspect 都是已落地的合法改动，不 revert

**D2. §一 memory schema 描述更新为 5.11（含 5.10 + 5.11 增量），删掉「SCHEMA_VERSION=58」残留**

- 不再写「SCHEMA_VERSION=58 未 bump」 —— 实际是 511 已 bump
- 5.10 + 5.11 增量分别简述（5.10 TTL / 5.11 LFU）

**D3. §二 §四 scoring/ 描述从「占位」改为「v0.4 baseline 已 ship」**

- 列出 `score_turn` + 3 常量 (`SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE`)
- 不动 ROADMAP.md（独立 doc，本 ADR 范围外）

**D4. §二模块清单补 `snapshot/inspect.py` 描述**

- 不写内部实现（避免越界），只补文件存在 + 与 `_tag_index` 同目录的共享关系

**D5. §五版本对照表补 5 行**

- 与 ADR-0023 标题清单完全对齐：5.10/5.11 schema + v0.4 scoring baseline + snapshot/inspect + v0.10 print_guard

**D6. C 类残留只标注不删**

- `main.py.bak` untracked — 不进 doc（drift scan 不应 dict untracked 备份；显式 HITL 留给后续 round）
- `manager.py.bak.5.10` tracked — 在 §二 memory/ 模块清单加一行备注

**D7. 顶部 ADR 清单加本 ADR-0025**

## 四、落地范围（本 ADR commit 同步落地的 doc 修复）

| Drift | 修复位置 | 修复内容 |
| --- | --- | --- |
| A1 | §一 记忆行 | schema 5.9 → 5.11 + 补 5.10/5.11 增量 + 删 `SCHEMA_VERSION=58` 残留 |
| A2 | §二 scoring/ 段 + §四 scoring/ 不变量行 + 顶部 ADR-0017/0022/0023 措辞 | 「占位仅 pycache」 → 「v0.4 baseline 已 ship (score_turn + 3 常量)」 |
| A3 | §五版本对照表 | 补 v0.4 / v0.5.10 / v0.5.11 / v0.10 print_guard 增量 / snapshot/inspect (round 421) 共 5 行 |
| B1 | §二 snapshot/ 段 | 补 `inspect.py` 模块描述 |
| B2 | 与 A2 一并 | （同 A2） |
| C1 | 不进 doc | 留待后续 round 显式 HITL |
| C2 | §二 memory/ 段 | 加一行备注「`manager.py.bak.5.10` 迁移前快照，git tracked 不删」 |

## 五、未做（决策留给后续 round）

- **ROADMAP.md v0.4 节**仍写「计划」但代码已 ship —— ROADMAP drift 不在本 ADR 范围
- **`main.py.bak` untracked 残留** —— 不 dict untracked 备份是 scanner 边界，清理决策留给显式 HITL
- **`memory/manager.py.bak.5.10`** —— 已 git tracked 且 D6 决策保留，不删
- **§五版本表 v0.5.10/5.11 commit hash 精确化** —— 已知是 `cb13c186` 父链，本 ADR 不强制改原文
- **5.11 schema 在 ROADMAP.md 的位置** —— ROADMAP 独立 doc，不在本 ADR 范围

## 六、与前序 ADR 的关系

- **ADR-0023 标题**就列了「5.10/5.11 schema + v0.4 scoring baseline + snapshot/inspect + v0.10 print_guard 二次入表」 —— 本 ADR-0025 把这 4 项**实际补到 §五版本表**
- **ADR-0024** (round 582) 落地的是 web_search 限流 + autonomous journal + rng，不覆盖 ADR-0023 清单 —— 互补关系，不是覆盖
- **ADR-0022 / 0021 / 0020 / 0018 / 0017** 都涉及 scoring 占位描述 —— 本 ADR 一次性更新到位
- **ADR-0013 D8** 删的是 `manager.py.bak`（无后缀）；本 ADR-0025 D6 标注保留的是 `manager.py.bak.5.10` —— 文件名不同，决策互补
- **ADR-0014** 「`SCHEMA_VERSION=58` 未 bump 是已知遗留」 —— 本 ADR-0025 一次性更正（实际是 511）

## 七、可验证检查

```bash
# A1 schema 5.11 验证
grep -nE 'SCHEMA_VERSION|_migrate_v51[01]|access_count' src/xragent/memory/manager.py | head -5
# 期望: SCHEMA_VERSION = 511  # 5.11

# A2 scoring baseline 验证
git ls-files src/xragent/scoring/
# 期望: __init__.py + score.py 两个文件都出现

# B1 snapshot/inspect 验证
git log --oneline -- src/xragent/snapshot/inspect.py | head -3
# 期望: 467bf563 autonomous: 加新功能小而具体 (round 421)

# C1 main.py.bak untracked 验证
git log -- src/xragent/main.py.bak
# 期望: 空输出（untracked）
```