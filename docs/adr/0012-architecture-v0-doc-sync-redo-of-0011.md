# ADR-0012 — architecture-v0.md 兑现 ADR-0011 重做版的 doc sync（v0.2.10 + v0.2.11）

> 本 ADR 是 **ADR-0011 重做版承诺的 doc sync**。ADR-0011 .md 文件已存在（v0.2.10 + v0.2.11 范围，commit `8ce44668` → 多次 Reapply → 当前 `1535e59e`），但其 §二 / §五 / §一 / 顶部链接的全部 doc 改动**自始未落地**——唯一一次落地尝试（commit `4f970a4d`）在 8 分钟后被 `6b7f3a99` revert。本 ADR 把该 sync 真正写到 `docs/architecture-v0.md`。

## 0. 触发与状态

| 项 | 值 |
| --- | --- |
| 触发 commit | `c9ea4bb9`（v0.2.10 refactor(registry) 抽 `_safe_call`）<br>`213da37f`（v0.2.10 compression/hook import 整理）<br>`65b75fae`（v0.2.11 autonomous.py 4 处清理，含 `window_s` 参数）<br>`43f68ada`（manager.py.bak 落盘，round 147）<br>`91ea0843`（`__tools_probe__.txt` 探针残留，min_diff_bytes gate 同期） |
| 上游 ADR | ADR-0011（v0.2.10 + v0.2.11 重做版，已落盘 .md） |
| 落地尝试 | commit `4f970a4d`（2026-07-31 08:57）→ 8 分钟后被 `6b7f3a99` revert，无明确原因 |
| architecture-v0.md 改动 | §一 自驱动段 +1 行（`window_s`）<br>§二 `tools/registry.py` 行 3 → 11 行（v0.2.10 内部结构）<br>§二 `memory/manager.py` 行 +3 行（manager.py.bak 留痕）<br>§二 `compression/hook.py` 行 +1 行（import 整理说明）<br>§二 `autonomous.py` 行注释更新（next_task 带 `window_s`）<br>§二 树末尾前补 1 行 `__tools_probe__.txt`<br>§五 +2 行（v0.2.10 + v0.2.11）<br>顶部 ADR 链接列表 +1 行（ADR-0011） |

## 1. 决策（Design Decisions）

### D1 — `tools/registry.py` 不再是"薄壳工厂函数"，是完整注册中心，doc 必须展开

**事实**：v0.2.10 commit `c9ea4bb9` 抽出 `_safe_call` helper 后，registry.py 演化到 305 行，包含：

  * `ToolDef` dataclass（`name`/`description`/`input_schema`/`risk`/`handler`）
  * `ToolRegistry` class 六方法：`register` / `unregister` / `get` / `names` / `specs` / `run`
  * 5 个 module-level helper：
    * `_HitlRejected` sentinel（避免 rejection 走 handler 异常分支）
    * `_HitlOutcome` NamedTuple（`_apply_hitl` 返回：args / approved / rejected）
    * `_call_gate(gate, req)`：兼容 callable gate 与 `.request()` 对象两种 HITL gate 形态
    * `_apply_hitl(name, td, args, gate)`：低风险 / `gate=None` 时直通；高风险走审批，决策 `args`/`approved`/`rejected`
    * `_safe_call(handler, args)`：handler 抛 `Exception` 统一包 `{"ok": False, "error": "<TypeName>: <msg>"}` envelope；
      `BaseException`（`KeyboardInterrupt` / `SystemExit`）**不吞**，让 supervisor 接管

`run` 流程：HITL gate → `_apply_hitl` 决策 → rejected 走 `{"blocked_by": "hitl", ...}` envelope
→ 否则 `_safe_call(handler, args)` 包异常 → approved 加 `hitl_approved: True` 字段。

**决策**：architecture-v0.md §二 `tools/registry.py` 行从 3 行展开到 11 行（注释里画
`ToolDef` dataclass + `ToolRegistry` class 六方法 + 5 module-level helper + `run` 完整流程）。

**理由**：doc 只写"注册 17 个工具"会让读者误判这是个 50 行工厂函数；实际 305 行是
核心注册中心，未来新增 helper 必须先看这一段。

### D2 — `src/xragent/memory/manager.py.bak` 留痕，不立刻删

**事实**：`manager.py.bak` 是 schema 5.5 之前快照（round 147 commit `43f68ada`），git tracked，
当前大小 **2852 bytes**（注意：ADR-0011 D2 写的是 1055 bytes，那是 v0.2.10 当时大小，
本轮 D6-5 残留扫描时已增长），**当前不被 import**（`grep -r "manager.bak" src/` 为空）。

**决策**：architecture-v0.md §二 `memory/manager.py` 行下加 3 行注释，明说：
  - 是 schema 5.5 之前快照（round 147，commit `43f68ada`）
  - git tracked，当前不被 import
  - **清理决策留给后续轮次**（理由：备份文件本身没坏处，删它等于丢掉 schema 5.5 之前
    的实现细节，可能影响未来"回滚到 5.5 schema"场景）

**理由**：git tracked 文件不进 doc 等于"幽灵资产"——新读者 `git ls-files` 看到它会困惑。

### D3 — `src/xragent/__tools_probe__.txt` 探针残留留痕

**事实**：`__tools_probe__.txt` 大小 47 bytes（`probe 1785260823 — diagnostic for write_file`），
git tracked，commit `91ea0843`（min_diff_bytes gate 探针同期），**当前不被 import**。

**决策**：architecture-v0.md §二 末尾 `/` 之前补 1 行（不放在某个模块下面，因为它
是仓库根 src/xragent/ 下的独立文件）：

```
├── __tools_probe__.txt        # 47 bytes 探针残留（commit 91ea0843 同期，git tracked，
│                             #           当前不被 import，清理决策留给后续轮次，见 ADR-0011 D3）
```

**理由**：与 D2 同构——git tracked 文件不列 doc 就是"幽灵资产"。

### D4 — autonomous.py 加 `window_s` 参数（公开 API 表面扩展）

**事实**：v0.2.11 commit `65b75fae` 给 `next_task` 加了 `window_s: float = DEFAULT_COOLDOWN_S`
参数（4 处清理之一），理由：测试时需短时间绕过 cooldown，不能改 module 常量污染其他测试。

`next_task` 当前签名（grep 验证）：

```python
def next_task(
    rng: random.Random | None = None,
    window_s: float = DEFAULT_COOLDOWN_S,
) -> dict[str, Any]:
```

**决策**：architecture-v0.md §一"自驱动（autonomous）"段补 1 行说明 `window_s`；
§二 `autonomous.py` 行注释里把"公开 API"签名更新为带 `window_s` 的版本。

**理由**：公开 API 签名变了不写到 doc，下次 ADR-0004 / ADR-0010 一类的"工具面变化"
审计会漏掉 autonomous.py 内部的 API drift。

### D5 — `compression/hook.py` import 整理不留 doc 章节，但注 1 行

**事实**：commit `213da37f` 把 `from .simple import SimpleCompression` 从文件底部挪到顶部
import 块，删掉 `# noqa: E402`，注册语句移到 `REGISTRY` 之后。当前 `head -20` 验证：

```
from __future__ import annotations

from typing import Any

from .simple import SimpleCompression
```

无 `noqa` 残留，顶部 import 块整齐。✓

**决策**：architecture-v0.md §二 `compression/hook.py` 行注释加 1 行说明"v0.2.10 import
整理（顶部 import + 无 noqa；见 ADR-0011 D5）"。**不开新章节**——这一改动是局部清理，
不是架构层。

**理由**：区分"架构变化"（开 ADR 章节）vs"局部清理"（1 行注）——避免 ADR 膨胀成"啥都记"的杂物筐。

### D6 — 自检约束（沿用 ADR-0011 D6-*）

**D6-1**（沿用 ADR-0006）：本 ADR 改完 `docs/architecture-v0.md` 后必须 `git diff --stat`
看 diff size 是否合理（不应 > 60 行净增）。
**D6-2**（沿用 ADR-0006）：跑 `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no`
看 fail 数；pre-existing fail 必须与本轮**无关**才能 commit。
**D6-3**（沿用 ADR-0006 / ADR-0009）：用 `grep -F '<关键串>'` 确认 doc 里的关键
字符串（如 `ToolRegistry` / `_safe_call` / `manager.py.bak` / `window_s`）真的在 doc 里出现。
**D6-4**（沿用 ADR-0010）：公开 API 签名变更必须写 doc，不留暗坑。
**D6-5**（沿用 ADR-0011 D6-5）：每次开 architecture-v0 同步类 ADR 必须做**残留文件扫描**——

  ```bash
  git ls-files src/xragent/ | grep -E '\.(bak|txt|md|json)$|~$|\.swp$'
  ```

  输出若包含 `.py.bak` / `~` / `.swp` / 测试残留的 `.txt`，必须在 doc 里留痕。

**理由**：D6-5 是 ADR-0011 v1 被 revert 后才固化的反例流程，必须每轮执行。

### D7 — 范围限定：本 ADR 只动 architecture-v0.md + ADR 文件本身

**事实**：扫描发现 README.md（line 107 仍写"9 工具"）、ROADMAP.md（v0.1 仍写"9 工具"）、
docs/agent-capabilities.md（line 6 仍写"10 个"）也都有 tool count drift，与本 ADR-0011
重做版的范围不一致。

**决策**：本 ADR **只动 docs/architecture-v0.md 与 docs/adr/0012-*.md**。README / ROADMAP /
agent-capabilities 三处的 tool count 修复留给**单独**的后续 ADR（tool count 跨文档 sync）——
避免本 ADR 范围爆炸（与 ADR-0005 → ADR-0006 的教训同构："啥都记"的 ADR 难 review、
难稳定落地）。

**理由**：每个 ADR 限定单一范围，便于 review / revert / 重做。

## 2. 实施步骤

1. 写 `docs/adr/0012-architecture-v0-doc-sync-redo-of-0011.md`（本文）
2. 改 `docs/architecture-v0.md`：
   * 顶部 ADR 链接列表 +1 行（ADR-0011）
   * §一 自驱动段补 `window_s` 说明
   * §二 `tools/registry.py` 3 → 11 行
   * §二 `memory/manager.py` +3 行（manager.py.bak）
   * §二 `compression/hook.py` +1 行（import 整理）
   * §二 `autonomous.py` 注释更新（next_task 带 `window_s`）
   * §二 末尾补 1 行 `__tools_probe__.txt`
   * §五 +2 行（v0.2.10 + v0.2.11）
3. 跑自检 D6-1 ~ D6-5
4. `git add -A && git commit -m "docs: ADR-0012 — 兑现 ADR-0011 重做版的 doc sync (v0.2.10 + v0.2.11)"`

## 3. 自检结果（本轮）

待执行（§3 末尾填实际命令输出）。

## 4. 回滚预案

若本轮 commit 被 revert：
1. 检查 revert commit message 看具体问题（多半是"残留文件扫描漏 / 签名漂移漏 / 范围爆炸"）；
2. 按 ADR-0008 经验，**整篇重写比补丁更稳**——开 ADR-0013，固化漏点到 D6-*；
3. 重点关注 D7（范围限定）是否被违反——若 README / ROADMAP / agent-capabilities 的
   tool count 修复也夹带进来，先 revert 再重做范围更小的版本。

## 5. 与 ADR-0005 / ADR-0006 / ADR-0008 / ADR-0011 重做模式的对比

| ADR | 前一版问题 | 重做方式 |
| --- | --- | --- |
| ADR-0005 | v0.2.5 首次 sync 不全 | ADR-0006 重做，把"自愈不变量"单列 |
| ADR-0008 | v0.2.7 两次 revert | ADR-0008 重做，固化为"schema + util 一起 sync" |
| ADR-0011 v1 | v0.2.10 sync 缺 manager.py.bak / __tools_probe__.txt / hook.py import / autonomous window_s | ADR-0011 v2 重做，范围扩大到 v0.2.10 + v0.2.11，新增 D6-5 残留文件扫描 |
| **ADR-0012** | ADR-0011 v2 全部 doc 改动自始未落地（commit `4f970a4d` 被 `6b7f3a99` revert），文档漂移累计 8 项 | **本 ADR**，把 ADR-0011 v2 承诺的 8 项 doc 改动逐项落地 + 加 D7 范围限定避免爆炸 |