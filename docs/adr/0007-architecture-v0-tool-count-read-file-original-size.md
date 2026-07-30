# ADR-0007: 架构 v0 工具面与 read_file 契约同步

- 状态: 已接受
- 日期: 2026-07-31
- 范围: `docs/architecture-v0.md` 与 `src/xragent/` 漂移对齐
- 取代: 无（增量补正）

## 一、背景

`docs/architecture-v0.md` 自 v0.2 起将「工具总数 / 工具表 / 不变量」作为事实表。
但 round 9b21c43a（`snapshot_cleanup` 暴露）与 round b0e0aa39（`read_file` 加 `original_size`）
落地后, doc 与 `src/xragent/tools/registry.py` 的事实逐渐漂移。

本次盘点发现 5 处过时/缺失, 用本 ADR 一次性纠正, 不动架构口径。

## 二、问题

### 2.1 工具总数漂移

| 位置 | 文档旧值 | 实际 (registry.py add() 计数) |
|------|---------|-----------------------------|
| §二 "工具总数" | **15** / evolution-off 时 13 | **17** / evolution-off 时 15 |
| §三 表标题 | "注册工具（15）" | 应为 "注册工具（17）" |
| §四 不变量 | "14 → 15 与 §三 一致" | 应为 "15 → 17 与 §三 一致" |

registry 实际 17 个 `add()` 调用, 分别为:

> read_file, list_dir, write_file, run_cmd, git_commit, git_push,
> snapshot_cleanup, memory_save, memory_recall, memory_recall_range,
> memory_top_frequent, memory_recall_by_tag, diary_write,
> propose_self_replace, curl_url, web_search, terminate

按风险分: low 8, medium 3, high 6 (与 §三 表一致)。

### 2.2 §三 表缺两行

- `snapshot_cleanup` (medium, git_tools.py) — round 9b21c43a 把
  `SideGit.cleanup_old_snapshots` 暴露成工具, 给父母定期清理 snapshot/*.tar.gz 用。
- `memory_recall_by_tag` (low, memory_tools.py) — round 与 memory schema 5.x
  的 `tags` 字段同步暴露 (save 时可选 `tags=[...]`, recall_by_tag 按交集过滤)。

### 2.3 §二 模块清单注释过期

`memory_tools.py` 注释 "4 个 memory_* 工具 (save + 3 种 recall, 见 ADR-0004)"
— 实际 5 个 (`save` + `recall` + `recall_range` + `top_frequent` + `recall_by_tag`)。

### 2.4 read_file 契约演进

`src/xragent/tools/fs_tools.py::read_file` 在 v0.3 (round b0e0aa39) 新增
`original_size` 字段, 用于截断 (`max_bytes`) 场景下让父母看到文件真实大小。
doc 原本的 read_file schema 只有 `content` / `truncated` / `size` 三字段。

### 2.5 memory schema 版本号

doc §二 仍只提 "见 ADR-0004" (memory schema 5.0)。
实际 schema 已迭代至 5.7 (`tags` / `title` / `confidence` / `archived` /
`priority` / `category` 派生等), 由 ADR-0004 后多轮叠加。
本次不展开 (避免偏离"工具表"主题), 在 v0.4 规划里单独立 ADR-0008 收纳。

## 三、决定

| # | 动作 | 文件 |
|---|------|------|
| 1 | §三 表标题 15 → 17, 加 `snapshot_cleanup` + `memory_recall_by_tag` 两行 | `docs/architecture-v0.md` |
| 2 | §二 "工具总数" 15/13 → 17/15, 模块清单 memory_tools 注释 4 → 5, git_tools 注释加 `snapshot_cleanup` | `docs/architecture-v0.md` |
| 3 | §四 不变量 "14 → 15" → "15 → 17" | `docs/architecture-v0.md` |
| 4 | §五 版本对照表加 v0.3.0 行 (read_file.original_size) | `docs/architecture-v0.md` |
| 5 | 本 ADR 留痕 | `docs/adr/0007-...md` |

口径不变:
- 风险分 (low / medium / high) 仍是事实表的"事实"。
- evolution-enabled → 全 17, evolution-disabled → 15。
- read_file schema 是契约; `original_size` 仅在截断时与 `size` 不同, 不破坏既有调用。

## 四、后果

- 未来新增工具继续按 "registry.add() 一处加, doc §三 同步加一行" 的双轨维护。
- memory schema 5.x 全量说明留给 ADR-0008 (v0.4 阶段), 本 ADR 不再展开。
- 保持本 ADR 是纯文档同步, 不动 src/。

## 五、参考

- ADR-0002: 工具表 (low/medium/high) 风险分口径。
- ADR-0003: evolution_enabled 开关语义。
- ADR-0004: memory schema 5.0 基线。
- ADR-0005: snapshot 与 cleanup 边界。
- round b0e0aa39: read_file.original_size 引入 commit。
- round 9b21c43a: snapshot_cleanup 暴露 commit。