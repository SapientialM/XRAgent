# ADR-0002: architecture-v0.md 同步刷（util 模块数 / CLI flags / 压缩 hook 状态）

- 状态：已接受（v0.1.1 增量，autonomous round 触发）
- 日期：2026-07-30
- 决策者：XRAgent（autonomous TASK_TEMPLATES["写 ADR 设计决策"]），经 HITL 审批 + supervisor 守护
- 触发任务：`TASK_TEMPLATES[6]` —— "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"

## 背景

`docs/architecture-v0.md` 是 v0.1 出生版地图，承诺"代码与文档同步"。v0.1.1 在五个
round 内的实际增量让若干处描述过时或缺失：

1. **util/ 模块数失实**：文档列 3 个，实际 5 个。
2. **CLI flags 不全**：文档漏列 `--interval` / `--max-rounds`。
3. **压缩 hook 状态错位**：文档把"压缩 hook 启用"放到 v0.3，但代码已在 v0.1 接入。
4. **缺少文档 / 代码单一真相源约定**：没有显式规则说明"代码与文档冲突时听谁的"。
5. **缺少交叉引用**：新出现的 `docs/agent-capabilities.md` 与 `docs/adr/` 未被架构文档链接。

## 决策

### D1. 同步 util/ 模块清单

将 §一 补充说明从 3 模块更新为 5 模块（新增 `diary_archive` + `git_helpers`），并在 §二 模块清单的
`util/` 行标注"5 模块，详见 §一"。

不新写 ADR 解释这两个模块的由来——它们是 ADR-0001 D1 原则的延续增量，原则不变。

### D2. 补全 main.py CLI flags

将 `--interval`（int，默认 30）和 `--max-rounds`（int，默认 0=无限）显式列入 §二 main.py 描述。
两个 flag 都仅作用于 `--autonomous` 分支（`cmd_autonomous`），由 argparse 透传。

### D3. 压缩 hook 标记为"已接入"而非"待启用"

- **现状**：`react_loop.py:72` 在每轮 ReAct 调用 `self.memory.compress_if_needed(messages,
  s.context_budget_tokens, s.compress_target_ratio)`；`memory/manager.py::compress_if_needed` 委托给
  `compression/simple.py::SimpleCompression`；`compression/hook.py::register("simple", SimpleCompression)` 已注册。
- **决策**：v0.1 的"压缩 hook 启用"任务实际已完成，v0.3 改名"强化"——保留 hook 注册表的可扩展性
  （用户可 `register("rolling", RollingCompression)` 热替换），新增按 category 索引 + 压缩比例自适应。
- **文档改动**：§一补充说明加压缩策略小节；§七 v0.3 描述从"启用"改为"强化"；ROADMAP.md
  不在本 ADR 范围内，留作后续 autonomous round 单独刷。

### D4. 加入"代码 / 文档单一真相源"约定

§四 关键不变量新增第 7 条：

> **代码 / 文档单一真相源**：当代码与本文档冲突时以代码为准，差异在 `docs/adr/` 留痕。

理由：v0.1.1 已证明文档滞后于代码是常态（本次 5 处失实只是冰山一角），没有显式规则
会让后续 autonomous round 不知道该改代码还是改文档——以及改成什么。ADR-0001 已示范过
这个流程，本次沿用。

### D5. 增加交叉引用

§末新增"相关文档"区块，链向 `agent-capabilities.md` / `adr/0001-*` / `adr/0002-*` / `ROADMAP.md`。
便于后续 autonomous round 沿引用链自查漂移。

## 影响

- **代码**：本次零代码改动，纯文档同步。
- **测试**：无新增测试；既有 95 用例与本次改动正交。
- **风险**：文档错位会导致未来 autonomous round 沿错的方向进化（如以为压缩 hook 还没接，
  重复实现一遍）。本次修复消除此风险。
- **可逆性**：纯文档，可 git revert 单点回滚。

## 遗留（不在本 ADR 范围）

- `src/xragent/memory/manager.py.bak` 仍残留在仓库内，应清理（v0.1 期间某次重构的备份）。
  待后续 autonomous round 起一个"清理 stale .bak"任务，不在本 ADR 拍板。
- `autonomous.py::_recent_titles` docstring 写"同 title 1 小时内不重复"，但 `DEFAULT_COOLDOWN_S=7200`（2h）。
  内部 docstring 与常量冲突，待单独 PR 修。