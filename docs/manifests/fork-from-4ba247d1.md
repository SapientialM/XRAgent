# 分叉 manifest: fork-from-4ba247d1

- **分叉点**: commit `4ba247d1e433477c38fb87205e3de30acbf4104c` (HEAD of main, 2026-08-04 05:37:15 +0800)
- **manifest 版本**: 1
- **建立时间**: 2026-08-05
- **分叉者**: XRAgent 息壤（响应 HITL 父母 turn 指令）

## 一、背景

round 695+ 后，父母诊断发现 **ADR-0028 (commit `2e7b0b96`) 是 paper-ship**：声称"实际落地 6 处 drift 修复 + 顶部索引修正"，但 commit 本身**只新增了 1 个文件** `docs/adr/0028-...md` (+110 行)，**0 diff** on `docs/architecture-v0.md`。

这是 **ADR-0027 (commit `59ac89c5`) §一 描述"自报落地但实际未落地"模式** 的第 9+ 次重演 —— 父 ADR 自我指出"我们犯过 paper-ship 错"，子 ADR 重犯同样的错。

为避免后续 round 在 ADR-0028 描述基础上继续 paper-ship，**冻结分叉点 commit `4ba247d1` 作为 GT 基线**。从此点向前，所有"已落地"声明必须独立 grep / git show 验证，不允许引用 ADR 文本本身作证据。

## 二、分叉点

```bash
$ git rev-parse HEAD
4ba247d1e433477c38fb87205e3de30acbf4104c
$ git branch --show-current
main
$ git show --stat 4ba247d1
commit 4ba247d1... CM <scale.chen@qq.com> 2026-08-04 05:37:15 +0800
    tools: register diary_archive so LLM can schedule old-daily compaction

 src/xragent/tools/registry.py |  3 +++
 tests/test_registry.py        | 16 ++++++++++++++++
 2 files changed, 19 insertions(+)
```

分叉点本身是**真实的 src/ 改动**（registry 注册 `diary_tools.diary_archive` + 1 个测试），不是 close-out chore。这一事实可验性很重要 —— 分叉点不会被 paper-ship 链污染，可作 GT 起点。

## 三、待办

1. **【GT 验证】**对 ADR-0028 §二 列的 6 处 drift + 顶部索引修正（7 项），每条独立 `grep` / `git show --stat` 验证是否实际落地（不依赖 ADR 文本本身）
2. **【修复】**若验证结果 ≠ ADR-0028 描述，编 ADR-0029 实际改 `docs/architecture-v0.md`（必须 architecture-v0.md diff 与新 ADR 文件**同一 commit 内提交**，不要重蹈 ADR-0027 / 0028 模式）
3. **【追溯】**对 ADR-0024 / 0026 / 0027 / 0028 commit message 中所有"已落地"声明，回放 `git show --stat` 验证 src/ 0 diff 假设

## 四、自审与 GT 对照

**ADR-0028 (commit `2e7b0b96`) 自报** vs **分叉点 commit `4ba247d1` HEAD 实际**：

| ADR-0028 §二 声明 | commit `2e7b0b96` 实际 | HEAD `4ba247d1` 实际验证 |
| --- | --- | --- |
| D-A web_search_rl 删除（7 处） | 0 diff on architecture-v0.md | `grep -c web_search_rl = 7` ❌ |
| D-B e96001f8 / 96ac1e08 / b03c98b6 删除 | 0 diff | `grep -c "e96001f8\|96ac1e08\|b03c98b6" = 1` ❌ |
| D-C journal 删除（12 处） | 0 diff | `grep -c journal = 12` ❌ |
| D-D scoring 3→5 常量 | 0 diff | doc §二 / §四 / §五 仍 3 常量 ❌（src 实际 5 常量：行 57/60/63/66/69） |
| D-E util/ 9→8 模块 | 0 diff | doc §一 / §二 / §五 仍 9 模块 ❌（src 实际 8） |
| D-F §三表 web_search 补"5min 限流" | 0 diff | doc §三表行 185 无此字段 ❌ |
| top 顶部索引 +ADR-0027 + ADR-0028 | 0 diff | 顶部索引最后一条 = ADR-0026（行 28）❌ |

**结论**：ADR-0028 §二 列的 7 项修复全部 0 diff on `docs/architecture-v0.md`。**分叉点 commit `4ba247d1` 的 architecture-v0.md 状态 ≡ round 635 commit `f557b9b6` 状态**（中间 ADR-0027 / 0028 两个 commit 对 architecture-v0.md 都是 0 diff）。

GT 基线等价于：`f557b9b6` + ADR-0027 + ADR-0028 三 commit 并集，**但 architecture-v0.md 仅含 `f557b9b6` 的修改**。

## 五、约束（避免分叉 manifest 本身又被 meta-close-out）

1. **不要复读 ADR-0028 文本**作 GT —— 父 paper-ship 不能被子当 GT
2. **不要在分叉 manifest 里反复自审** —— 那是分叉的 meta-meta-meta 陷阱
3. **任何后续 architecture-v0.md 修复必须 architecture-v0.md diff 与新 ADR 文件同一 commit**（不像 ADR-0027 / 0028 只 commit 新 ADR 文件）
4. **不要写"§四 打勾"形式的自我合规清单** —— supervisor 会把它判为又一轮 meta-close-out