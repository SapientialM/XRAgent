# ADR-0003：snapshot 保留策略 + 架构文档与代码同步

- 状态：已采纳
- 日期：2026-07-30
- 触发者：autonomous round（N=…；turn "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"）
- 相关 commit：`66f601f0 snapshot v0.2.3: cleanup_old_snapshots + snapshot_retention_days`
- 相关文档：[`docs/architecture-v0.md`](../architecture-v0.md)

## 背景

`docs/architecture-v0.md` 自称是"v0.1 出生时的快速地图"，并在文首声明：

> 当代码与本文档冲突时：**代码为准**，并在 `docs/adr/` 记录决策。

ADR-0002 已对 util 模块数 / CLI flags / 压缩 hook 状态做了一次 sync（commit `04cf9ffe`）。

此后 commit `66f601f0`（v0.2.3）又新增了两处 API 与配置：

1. `src/xragent/snapshot/side_git.py::SideGit.cleanup_old_snapshots(
     max_age_days: int | None = None,
     dry_run: bool = False,
   ) -> list[str]`
   - 仅匹配 `xragent/turn-*` 前缀的 snapshot tag；用户手工 tag（`v0.1` / `baseline`）不误删
   - `max_age_days <= 0` 静默返回 `[]`（用于禁用开关）
   - `dry_run=True` 仅列候选
   - 非 git 仓库 / 单条 tag 删不掉均不阻塞整体
   - 由 `creatordate:unix` 排序，删最旧的
2. `src/xragent/config/settings.py::Settings.snapshot_retention_days: int = 30`
   - `cleanup_old_snapshots()` 在 `max_age_days=None` 时读此值

附带测试：7 个 case 全过（`tests/test_sidegit_cleanup.py`）。

## 文档漂移

`docs/architecture-v0.md` 在以下位置**未体现**上述新增：

- **§一「五大核心」记忆行**：只列 `snapshot/side_git.py` 为"每个 turn snapshot"，
  未提保留策略与清理入口。
- **§二「模块清单」**：`snapshot/side_git.py` 一行注释只说"每个 turn snapshot"，
  没有 `cleanup_old_snapshots()` 这一行。
- **§四「关键不变量」**：6 条中没有"snapshot tag 保留天数可配"这一条。
- **§七「演进路线」v0.1 行**：仍写 "current"，但实际代码已演进到 v0.2.3。

按 ADR-0002 与本文档自身约定（代码为准 / 差异在 ADR 留痕），本次以 **新增 ADR** +
**对 architecture-v0.md 做最小增量**的方式补齐，不重写整篇文档（其"v0.1 出生版"
定位应保持）。

## 决策

### D1：补 ADR-0003 留痕

把 v0.2.3 引入的 API 与配置面记入 ADR（本文件），作为 "代码为准" 原则的存档。

### D2：architecture-v0.md 最小增量

不重写，只在四处加 1 行级注释，指向 ADR-0003：

1. §一 记忆行末尾加 "(v0.2+ 含 cleanup 入口，见 ADR-0003)"
2. §二 `snapshot/side_git.py` 行扩到两行：`snapshot/side_git.py` + `snapshot/...（v0.2.3 + cleanup_old_snapshots）`
3. §四 不变量新增第 8 条："snapshot 保留天数可配：`Settings.snapshot_retention_days`
   （默认 30）；≤0 禁用清理"
4. §七 v0.1 行加 "(实际已演化为 v0.2.3；增量见 ADR-0003)"

理由：保留文档作为"v0.1 出生版"的历史价值；同时让读者在 §一/§二/§四
任一处都能跳到 ADR-0003 看到当前真实 API。

### D3：清理策略是配置而非硬编码

`max_age_days=None` 时走 settings，而不是 hardcode 默认值。
理由：watchdog / cron 调用方可在不改代码前提下用单一开关关闭
（`snapshot_retention_days: int = 0` ⇒ `max_age_days <= 0` ⇒ 静默 `[]`）。

### D4：清理前缀必须严格 `xragent/turn-*`

`git for-each-ref refs/tags/xragent/turn-*` 做精确前缀匹配，避免误删：
- 用户手工里程碑 tag（`v0.1` / `baseline` / `release-x`）
- 其它自动 tag（如将来 `xragent/exp-*` / `xragent/baseline-*`）

## 后续

- 若 v0.3 引入 snapshot 压缩（去重 + gzip），在 ADR-0003 追加 D5。
- 若 §七版本表与代码漂移继续扩大，考虑把 architecture-v0.md 升到
  architecture-current.md + 旧版归档（不在本 ADR 范围）。

## 附：其它次要发现（本轮不修）

- `src/xragent/memory/manager.py.bak` 是 round 147 的旧备份，仍被 git 追踪。
  下次 autonomous round "加新功能小而具体" 时可一并清理。
- `cmd_interactive` 的 `/tools /memory /diary /snapshot /quit` 子命令未在
  architecture-v0.md 体现；属 CLI 细节，不影响架构决策，不纳入本 ADR。