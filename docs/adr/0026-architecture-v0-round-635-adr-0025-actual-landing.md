# ADR-0026: architecture-v0.md round 635 — ADR-0025 实际落地（schema 5.11 + scoring v0.4 + snapshot/inspect + §五补 5 行）

- **状态**: 已落地（仅 doc 同步，未碰 src/）
- **时间**: round 635 drift 扫描 + 落地
- **触发**: 父母指令「读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。必须 write_file 改 docs/architecture-v0.md 或加 docs/adr/0001-*.md。改完 commit。」
- **前置 ADR**: ADR-0025（round 588 设计但未落地）+ ADR-0024（round 582 实际落地 web_search 限流 / autonomous journal）+ ADR-0023（round 562 设计但未落地）
- **本 ADR commit**: 同 commit chain

## 一、问题陈述

ADR-0025 (round 588) 已经系统列出 10 项 drift（A1-A3 / B1-B2 / C1-C2）并给出 D1-D7 修复方案，
但其"已落地"声明的 commit chain 是空的（仅 `99f0564f` autonomous 写了 ADR-0025 文件本身）。
round 582 ADR-0024 落地的是 web_search 限流 + autonomous journal + rng，**未覆盖** ADR-0025 清单里的 4 项。

本轮按父母 turn 指令做实际 doc 同步：
- A1 schema 5.9 → 5.11（含 5.10 TTL + 5.11 LFU）
- A2 §二 §四 scoring/ 描述从「占位」改为「v0.4 baseline 已 ship」
- A3 §五补 5 行：v0.4 / v0.5.10 TTL / v0.5.11 LFU / v0.10 print_guard / snapshot inspect (round 421)
- B1 §二 snapshot/ 补 `inspect.py` 模块描述
- C2 §二 memory/ 补 `manager.py.bak.5.10` 迁移前快照备注
- D7 顶部 ADR 索引补本 ADR-0025 + 本 ADR-0026 两行

## 二、本轮实际 drift 确认（代码 vs doc 二次核对）

| Drift | 文档原句 | 代码实际 | commit |
| --- | --- | --- | --- |
| A1 | §一 / §四「当前有效 schema 5.9」「`SCHEMA_VERSION=58` 未 bump 是已知遗留」 | `manager.py` line 36 `SCHEMA_VERSION = 511  # 5.11`；line 338-339 `_migrate_v510()` + `_migrate_v511()`；Fact.access_count + expires_ts 已 ship | `cb13c186` |
| A2 | §二 / §四「scoring/ 占位包 v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked」 | `scoring/__init__.py` (827 bytes) + `scoring/score.py` (7980 bytes) 均 git tracked；导出 `score_turn` + 3 常量 | `8125486d` + `a1d51ee2` |
| A3 | §五版本对照表最后一条停在 v0.13.2 (round 582) | v0.4 / v0.5.10 / v0.5.11 / v0.10 print_guard / v0.5.x snapshot/inspect 五个 entry 都已 ship 未记 | 各自 commit |
| B1 | §二 snapshot/ 段只列 `_tag_index` / `age_cleanup` / `count_cleanup` / `side_git` | `inspect.py` (8466 bytes) git tracked，4 公开 API：SnapshotMeta / list_snapshots_with_meta / count_over_age / format_snapshot_table | `467bf563` |
| C2 | §二 memory/ 段 + §四不变量未提 `manager.py.bak.5.10` | 38755 bytes git tracked，commit `cb13c186` 同期「5.10 → 5.11 迁移前快照」 | `cb13c186` |
| D7 | 顶部 ADR 索引最新行是 ADR-0024 | ADR-0025 (round 588) + 本 ADR-0026 (round 635) 已存在 | 本 commit |

C1 类 `main.py.bak` (untracked) **不在本轮 doc 同步范围** —— ADR-0025 §五决策显式不 dict untracked 备份，cleanup HITL 留给后续 round。

## 三、修复范围（与 ADR-0025 D1-D7 完全对齐）

### D1（不变量）— 仅 doc 同步，不碰 src/

- 与 ADR-0022 / 0023 / 0024 / 0025 一致：drift 扫描目的是修正文档而非回滚代码
- 5.11 schema / v0.4 scoring / snapshot/inspect / print_guard 都是已落地的合法改动

### D2 — §一 memory schema 描述更新为 5.11

- 删「5.9」+ 「`SCHEMA_VERSION=58` 未 bump 是已知遗留」措辞
- 改为 5.11（5.10 TTL + 5.11 LFU 增量分别简述）
- 「有效口径以 `_migrate_all()` 实际跑到的最后一个版本为准」保留（口径对，版本号错）

### D3 — §二 §四 scoring/ 描述从「占位」改为「v0.4 baseline 已 ship」

- §二 line 152 + §四 line 214 两处「占位包 v0.13.1 状态」全段重写
- 列出 `score_turn` + 3 常量（`SCORE_ERROR` / `SCORE_OK_BASE` / `SCORE_RANGE`）

### D4 — §二 snapshot/ 段补 `inspect.py` 模块描述

- 与 `_tag_index` / `age_cleanup` / `count_cleanup` 平级
- 显式说明属「只读 + 展示」层（cleanup 是写入层），不引入 `git` 写操作

### D5 — §五版本对照表补 5 行

- v0.4 / v0.5.10 / v0.5.11 / v0.10 print_guard / v0.5.x snapshot inspect
- 与 ADR-0025 §四 A3 表逐行对齐

### D6 — §二 memory/ 段加 `manager.py.bak.5.10` 备注

- 一行备注：「迁移前快照，git tracked 不删，清理决策留给后续 round」
- 区别于 ADR-0013 D8 删的 `manager.py.bak`（无后缀）—— 文件名不同，决策互补

### D7 — 顶部 ADR 清单补本 ADR-0025 + ADR-0026 两行

- ADR-0025 已在 docs/adr/ 目录存在但顶部索引未引
- ADR-0026 为本轮新写

## 四、不在本轮范围

- **`main.py.bak` untracked 清理**：drift scan 不应 dict untracked 备份（边界），清理决策留给显式 HITL
- **ROADMAP.md v0.4 节措辞**：ROADMAP 独立 doc，本 ADR 不动
- **§五 v0.5.10/5.11 commit hash 精确化**：已知 `cb13c186` 父链，本 ADR 不强制改原文（ADR-0025 §五也是泛指）
- **5.10 TTL / 5.11 LFU 内部方法注册工具面**：`recall_unexpired` / `set_ttl` / `recall_most_accessed` 等未注册到 tools/registry.py（ADR-0025 D5），决策留给后续 round
- **§一 util/ 注释补 print_guard 二次入表**：ADR-0023 D1/D2/D9/D10 声称做了但实际 §一末尾"当前 8 个模块"+ §二 util/ 注释均漏 print_guard.py —— 这是 ADR-0023 自己的未落地清单，**本轮一并修复**（见 D2'）

### D2' — §一 §二 util/ 注释补 `print_guard.py`（ADR-0023 D1/D9/D10 二次落地）

- §一 line 52「当前 8 个模块」→ 「当前 9 个模块」+ print_guard.py
- §二 util/ 注释末尾「8 个模块」→ 「9 个模块」+ print_guard.py
- 这是 ADR-0023 早已设计但 round 582 / 588 都没真落地的二次入表

## 五、commit 计划

`docs(arch): ADR-0026 + sync architecture-v0.md (round 635 实际落地 ADR-0025 D1-D7 + D2' print_guard 二次入表)`

包含：
- ADR-0026 新文件（本文件）
- architecture-v0.md 8 处 str.replace 精确替换：
  1. 顶部 ADR 索引追加 ADR-0025 + ADR-0026 两行
  2. §一 util/「8 个模块」→「9 个模块」+ print_guard（v0.10 ADR-0018）
  3. §一 memory schema「5.9」→「5.11」+ 5.10/5.11 增量 + 去「SCHEMA_VERSION=58」残留
  4. §二 util/「8 个模块」→「9 个模块」+ print_guard
  5. §二 snapshot/ 段补 `inspect.py` 行
  6. §二 scoring/ 段「占位包」全段重写「v0.4 baseline」
  7. §二 memory/ 段补 `manager.py.bak.5.10` 备注
  8. §四 scoring/ 不变量行「v0.13.1 占位状态」全段重写「v0.4 baseline 已 ship」
  9. §五版本对照表补 v0.4 / v0.5.10 / v0.5.11 / v0.10 print_guard / v0.5.x snapshot inspect 共 5 行

实际为 9 处（覆盖 ADR-0025 D1-D7 + 本 ADR-0026 D2'）。

## 六、可验证检查

```bash
# A1 schema 5.11
grep -nE 'SCHEMA_VERSION|_migrate_v51[01]' src/xragent/memory/manager.py | head -5
# 期望: SCHEMA_VERSION = 511  # 5.11 + _migrate_v510/v511

# A2 scoring baseline
git ls-files src/xragent/scoring/
# 期望: __init__.py + score.py 两个文件都出现

# B1 snapshot/inspect
git log --oneline -- src/xragent/snapshot/inspect.py | head -3
# 期望: 467bf563

# D2' util/print_guard 二次入表
grep -n "print_guard" docs/architecture-v0.md | head -5
# 期望: §一 §二 util/ 注释都提到 print_guard.py
```

## 七、与前序 ADR 的关系

- **ADR-0025**：本 ADR 是其设计到落地的桥梁（drift 清单 + D1-D7 完全复用，仅补 D2' print_guard）
- **ADR-0023**：其 D1/D2/D9/D10 声称落地但实际未落地 —— 本 ADR-0026 D2' 二次落地
- **ADR-0024** (round 582)：落地的是 web_search 限流 + autonomous journal + rng，不覆盖 ADR-0025 清单 —— 互补
- **ADR-0013 D8**：删的是 `manager.py.bak`（无后缀）；本 ADR-0026 D6 标注保留的是 `manager.py.bak.5.10` —— 文件名不同，决策互补
- **ADR-0014**：其「`SCHEMA_VERSION=58` 未 bump 是已知遗留」 —— 本 ADR-0026 一次性更正（实际是 511）