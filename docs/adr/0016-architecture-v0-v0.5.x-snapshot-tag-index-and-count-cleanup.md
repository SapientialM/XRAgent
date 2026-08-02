# ADR-0016: architecture-v0 sync — v0.5.x snapshot 共享原语 + v0.11 数量兜底

> **状态**: 提案（pending apply）
> **影响**: `docs/architecture-v0.md`（§一 / §二 / §四 / §五 + 顶部 ADR 清单）
> **锚点**: ROADMAP.md v0.5.x "snapshot helper 收归 _tag_index" ✅ + v0.11 "SideGit snapshot cleanup 加 dry_run" ✅

## 0. 元数据

| 项 | 值 |
| --- | --- |
| 提出 | round 208+ (CM driver) |
| 触发 | 用户指令: "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。" |
| 上游 ADR | ADR-0015 (v0.5 schema 5.9 doc sync landing, commit `0f5232eb`) |
| 上游 commits | `a457993f` (v0.5.x _tag_index helper 抽出, 2026-08-03) / `a59beb18` (count_cleanup 走 _tag_index, 2026-08-03) / `0247b56b` (ROADMAP v0.5.x/v0.11 ✅, 2026-08-03) / `364285d8` (v0.5.6 _check_compile per-file timeout, 2026-08-02) / `b79130d3` (v0.5.6 _safe_decode 直测, 2026-08-02) |
| 已落地代码 | `src/xragent/snapshot/_tag_index.py` (4721 bytes, 73+ 行) + `src/xragent/snapshot/count_cleanup.py` (89 行) |
| 实际 src 行数 | `snapshot/_tag_index.py` 73 / `snapshot/count_cleanup.py` 89 / `snapshot/side_git.py` 399 |

## 1. 触发：架构 doc 与代码 drift

按用户指令 diff `docs/architecture-v0.md` vs `src/xragent/` 当前状态，找到 5 处 drift：

### D1. §二 模块清单 缺 2 个 snapshot 模块

| 文档现状 | 实际 | drift |
| --- | --- | --- |
| §二 仅列 `snapshot/side_git.py` + `snapshot/__init__.py` (隐式) | 新增 `snapshot/_tag_index.py` (4721 bytes) + `snapshot/count_cleanup.py` (3948 bytes, 89 行) | `__pycache__` 也已存在 (`snapshot/__pycache__/` 含 6 项) —— 模块清单已实质多 2 个模块 |

### D2. §四 "失败可回滚" 不变量描述不全

| 文档现状 | 实际 | drift |
| --- | --- | --- |
| "`SideGit.cleanup_old_snapshots` 每 turn tag + v0.2.3 后 `cleanup_old_snapshots` 自动清理过期 tag" | `count_cleanup.py::cleanup_old_snapshots_by_count(max_count, dry_run)` 按数量兜底 + `_tag_index.py` 提供 `list_xragent_turn_tags` / `parse_xragent_turn_tags` / `delete_tags` 三个共享原语 | 不变量**只覆盖按时间**，未提按数量兜底、未提共享 helper 收敛 —— 与"失败可回滚"的语义不对称 |

### D3. §五 版本对照缺 5 行

| 文档现状 | 实际 ROADMAP | drift |
| --- | --- | --- |
| §五 最后一行是 "v0.5 (✅ 部分) ... ADR-0014 / ADR-0015" | ROADMAP.md 已 ✅ 的项: v0.5.x "snapshot helper 收归 _tag_index" + v0.5.6 "`_safe_decode` 直测" + v0.5.6 "_check_compile per-file timeout (30s) + concurrent" + v0.5.7 memory PEP 604 docstring (`a457993f` 同期) + v0.5.8 count_cleanup 走 _tag_index (`a59beb18`) + v0.11 "SideGit snapshot cleanup 加 dry_run" | arch doc 完全空白；ROADMAP ✅ 但架构 doc 没体现 |

### D4. 顶部 ADR 链接表 缺 ADR-0016

| 文档现状 | 实际 | drift |
| --- | --- | --- |
| 顶部最后一条 `ADR-0015` | 本轮新增 ADR-0016 | ADR 索引未追平 |

### D5. §一 "记忆" 核心缺 snapshot 演进一行

| 文档现状 | 实际 | drift |
| --- | --- | --- |
| "memory/side_git.py (v0.2+ 含 cleanup 入口，见 ADR-0003)" | v0.5.x 后 `snapshot/` 含 3 模块（`side_git` + `_tag_index` 共享原语 + `count_cleanup` 数量兜底），v0.11 + `dry_run` | §一只有 side_git 一个名字，看不出 snapshot 子包已分化成 3 文件 |

## 2. 决策

### D1 应用方式

§二 模块清单 `snapshot/side_git.py` 描述后插入 2 个新模块：

```
├── snapshot/side_git.py       # 每个 turn snapshot
│                             # v0.2.3 新增 cleanup_old_snapshots()，见 ADR-0003
├── snapshot/_tag_index.py     # v0.5.x 抽出: list_xragent_turn_tags / parse_xragent_turn_tags
│                             #          / delete_tags 三个共享原语，让 cleanup 路径只剩策略
│                             #          (time-cutoff / count-slice)，不再重复 for-each-ref + 行解析
├── snapshot/count_cleanup.py  # v0.11: cleanup_old_snapshots_by_count(max_count, dry_run=False)
│                             #          按 creatordate 数量兜底，与 cleanup_old_snapshots 互不冲突
```

### D2 应用方式

§四 "失败可回滚" 不变量扩为 2 路径 + 共享 helper：

```
| 失败可回滚 | `snapshot/side_git.py` 每 turn tag + 两条清理路径:<br>· 时间维 `cleanup_old_snapshots(max_age_days, dry_run)` 保留近 N 天<br>· 数量维 `count_cleanup.cleanup_old_snapshots_by_count(max_count, dry_run)` 保留最新 N 个<br>两条路径共享 `snapshot/_tag_index.py` 三个原语（`list_xragent_turn_tags` / `parse_xragent_turn_tags` / `delete_tags`），行格式 `%09` / `\t` 改一处时不再漂移。`snapshot_cleanup` 工具同时挂载两条清理路径（见 ADR-0007 + ADR-0016） |
```

### D3 应用方式

§五 在 v0.5 (✅ 部分) 行后追加 5 行：

| 版本 | 关键事件 | ADR |
| --- | --- | --- |
| v0.5.6 | `evolve/metamorphosis.py` `_check_compile` per-file timeout (30s) + concurrent；`exec_tools._safe_decode` 直测 15 cases 锁契约 | ADR-0016 |
| v0.5.7 | `memory/manager.py` `_safe_create_index` 加 PEP 604 hint + Google docstring（2 hints） | ADR-0016 |
| v0.5.8 | `snapshot/_tag_index.py` 抽出 3 共享原语（`list_xragent_turn_tags` / `parse_xragent_turn_tags` / `delete_tags`），让 `cleanup_old_snapshots` + `cleanup_old_snapshots_by_count` 只剩策略；行格式 `%09` / `\t` 单点维护 | ADR-0016 |
| v0.5.9 | `snapshot/count_cleanup.py` 走 `_tag_index` helper（去掉 3 处 inline 重复）；保留 / 删除段用负索引 + 升序语义，无额外排序 | ADR-0016 |
| v0.11 | SideGit snapshot cleanup 加 `dry_run` 参数（按时间 + 按数量两条路径都加），仅列候选不实际 `git tag -d`；`snapshot_cleanup` 工具同步暴露 dry_run | ADR-0016 |

### D4 应用方式

顶部 ADR 清单追加一行：

```
> [ADR-0016](adr/0016-architecture-v0-v0.5.x-snapshot-tag-index-and-count-cleanup.md)（v0.5.6~v0.5.9 + v0.11：snapshot/_tag_index.py 共享原语 + snapshot/count_cleanup.py 数量兜底 + dry_run）。
```

### D5 应用方式

§一 "记忆" 行 `snapshot/side_git.py` 描述后插入一句（不破折现有结构）：

```
| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py`（v0.2+ 含 cleanup 入口，见 ADR-0003）<br>+ `snapshot/_tag_index.py`（v0.5.x 共享原语，见 ADR-0016）+ `snapshot/count_cleanup.py`（v0.11 数量兜底，见 ADR-0016）<br>...（剩余描述保持不变） |
```

## 3. 不做的项（沿用 ADR-0014 / ADR-0015 决策）

- 不 bump `SCHEMA_VERSION = 58` 常量（ADR-0014 决策，5.9 DDL-only 不增字段；本轮不动 memory）
- 不重写 §四 read_file / registry / autonomous 不变量（已分别在 ADR-0007 / 0011 / 0012 落地，无需再动）
- 不新增 v0.5.6 / v0.5.7 的 ADR 单独文件（属于"演化推进"+ "小修"，与 v0.5.9/_tag_index 抽出在同一个窗口，合并到 ADR-0016 即可；不制造 ADR 膨胀）
- 不改 ROADMAP.md（v0.5.x / v0.11 已 ✅；本轮是 arch doc 追 ROADMAP，不是反过来）
- 不动 src/（本轮纯 doc sync，baseline 866 tests 不受影响；snapshot 实际改进已分别落地在 a457993f / a59beb18 / 0247b56b）

## 4. 校验

- 5 处 drift 都有对应 anchor（旧字符串唯一）：
  - D1: `snapshot/side_git.py       # 每个 turn snapshot` 唯一锚（§二出现 1 次）
  - D2: "`snapshot/side_git.py` 每 turn tag + v0.2.3 后 `cleanup_old_snapshots` 自动清理过期 tag" 唯一锚（§四 1 次）
  - D3: v0.5 (✅ 部分) 行结尾 "见 ADR-0014 / ADR-0015" 唯一锚（§五 1 次）
  - D4: ADR-0015 链接行尾 "...ADR-0015)" 唯一锚（顶部 1 次）
  - D5: §一"记忆"行里 `snapshot/side_git.py` 描述唯一锚（§一 1 次）
- 所有替换走 `read_file` + `sed -i` Python 脚本，5 处独立编辑，commit message 列每处 +/- 行数
- 行数预算: D1 +5 / D2 +3 / D3 +7 / D4 +1 / D5 +2 = 总 +18 行，文件 ~22694 → ~22712 bytes
- UTF-8 + 中文 + 制表符全部保留

## 5. 落地步骤

1. `read_file docs/architecture-v0.md` 取当前精确字节
2. Python 脚本做 5 处 `replace(old, new, count=1)` 写入
3. `grep -c` 校验新 anchor 命中、旧 anchor 残留 = 0
4. `wc -l docs/architecture-v0.md docs/adr/0016-*.md`
5. `git add docs/adr/0016-*.md docs/architecture-v0.md`
6. `git commit -m "docs(arch): ADR-0016 + 5 处 drift 修复（v0.5.6~v0.5.9 + v0.11 snapshot 演化）"`
7. 等 supervisor 自动 push

## 6. 风险与回滚

- 风险：5 处 anchor 任一被未来 commit 改了锚字符串 → Python 脚本 `replace` 失败 → 整 commit 拒
- 回滚：`git revert HEAD --no-edit` （一次性 revert 不构成 ping-pong —— 上次 close-out↔revert ping-pong 在 round 33~35，已固化在 commit `31459d30` 之后；本 commit 是首轮 drift 修复，无历史 close-out↔revert 循环可触发）
- 不回滚意味着什么：5 处 drift 永远留在 doc；下一次 CM driver 巡检会再触发 ADR-0017，工作量更大

## 7. 下一步

- 应用 5 处 drift 修复（实际代码已 ready 落地）
- 跑 `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no` 验证 baseline 866 tests 不被 doc-only 变更影响（实际不需要 —— 纯 docs/，但 supervisor 风格是 sanity check）
- commit 后等 supervisor 自动 push