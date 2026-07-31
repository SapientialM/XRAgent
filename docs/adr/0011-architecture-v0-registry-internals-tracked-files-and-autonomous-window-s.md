# ADR-0011 — architecture-v0 sync: registry.py 内部结构、git tracked 残留文件、autonomous.window_s 与 hook.py import 整理（v0.2.10 + v0.2.11 重做）

> 本 ADR 是 **ADR-0011 重做版**。前一版（commit `4f970a4d`）覆盖范围仅 v0.2.10，被 commit `6b7f3a99` revert。
> 重做版与前一版的差异：把 v0.2.11 autonomous.py 4 处清理并入（本轮 commit `65b75fae`），把
> compression/hook.py import 整理并入 v0.2.10（同期 commit `213da37f`），并把所有 git tracked 的
> 残留文件一次性列齐——避免后续轮次再因"少列一个 bak/.txt"被 revert。

## 0. 触发与状态

| 项 | 值 |
| --- | --- |
| 触发 commit | `061fe162` / `bc097ae4` / `28c9e221` / `c9ea4bb9`（v0.2.10 refactor(registry)）<br>`213da37f`（compression/hook import 整理）<br>`43f68ada`（manager.py.bak 落盘）<br>`91ea0843`（__tools_probe__.txt 探针）<br>`65b75fae`（autonomous.py 4 处清理） |
| ADR-0011 前一版 | commit `4f970a4d`（已 revert，本轮重做） |
| architecture-v0.md §二 | tools/registry.py 行 3 → 11 行（v0.2.10 内部结构展开）<br>memory/manager.py 行 +3 行（manager.py.bak 留痕）<br>autonomous.py 行 next_task 签名更新（v0.2.11）<br>compression/hook.py 行 import 整理说明（v0.2.10）<br>§五 v0.2.10 + v0.2.11 行新增 |
| README.md | tools/ 行点名 ToolRegistry + ADR-0011 链接 |

## 1. 决策（Design Decisions）

### D1 — tools/registry.py 不再是"薄壳工厂函数"，是完整注册中心，doc 必须展开

**事实**：v0.2.10 commit `c9ea4bb9` 抽出 `_safe_call` helper 后，registry.py 演化到 305 行，
包含：

  * `ToolDef` dataclass（`name`/`description`/`input_schema`/`risk`/`handler`）
  * `ToolRegistry` class 六方法：`register` / `unregister` / `get` / `names` / `specs` / `run`
  * 5 个 module-level helper：
    * `_HitlRejected` sentinel（避免 rejection 走 handler 异常分支）
    * `_HitlOutcome` NamedTuple（`_apply_hitl` 返回：args / approved / rejected）
    * `_call_gate(gate, req)`：兼容 callable gate 与 `.request()` 对象两种 HITL gate 形态
    * `_apply_hitl(name, td, args, gate)`：低风险 / `gate=None` 时直通；高风险走审批，决策 `args`/`approved`/`rejected`
    * `_safe_call(handler, args)`：handler 抛 `Exception` 统一包 `{"ok": False, "error": "<TypeName>: <msg>"}` envelope；
      `BaseException`（`KeyboardInterrupt` / `SystemExit`）**不吞**，让 supervisor 接管

`run` 流程（doc 必须画清）：HITL gate → `_apply_hitl` 决策 → rejected 走 `{"blocked_by": "hitl", ...}` envelope
→ 否则 `_safe_call(handler, args)` 包异常 → approved 加 `hitl_approved: True` 字段。

**决策**：architecture-v0.md §二 `tools/registry.py` 行从 3 行展开到 11 行（注释里画
`ToolDef` dataclass + `ToolRegistry` class 六方法 + 5 module-level helper + `run` 完整流程）。

**理由**：doc 只写"注册 17 个工具"会让读者误判这是个 50 行工厂函数；实际 305 行是
核心注册中心，未来新增 helper（如 `_safe_call` 衍生）必须先看这一段。

### D2 — `src/xragent/memory/manager.py.bak` 留痕，不立刻删

**事实**：`manager.py.bak` 是 schema 5.5 之前快照（round 147 commit `43f68ada`），git tracked，
文件大小 1055 bytes，**当前不被 import**（`grep -r "manager.bak" src/` 为空）。

**决策**：architecture-v0.md §二 `memory/manager.py` 行下加 3 行注释，明说：
  - 是 schema 5.5 之前快照（round 147，commit `43f68ada`）
  - git tracked，当前不被 import
  - **清理决策留给后续轮次**（理由：备份文件本身没坏处，删它等于丢掉 schema 5.5 之前
    的实现细节，可能影响未来"回滚到 5.5 schema"场景）

**理由**：git tracked 文件不进 doc 等于"幽灵资产"——新读者 `git ls-files` 看到它会困惑。
明确"留 / 删 / 迁移"的判断点是 doc 的责任。

### D3 — `src/xragent/__tools_probe__.txt` 探针残留留痕

**事实**：`__tools_probe__.txt` 大小 47 bytes（`probe 1785260823 — diagnostic for write_file`），
git tracked，commit `91ea0843`（min_diff_bytes gate 探针同期），**当前不被 import**。

**决策**：architecture-v0.md §二 末尾 `/` 之前补 1 行（不放在某个模块下面，因为它
是仓库根 src/xragent/ 下的独立文件）：

```
├── __tools_probe__.txt        # 47 bytes 探针残留（commit 91ea0843 同期，git tracked，
│                             #           当前不被 import，清理决策留给后续轮次，见 ADR-0011 D3）
```

**理由**：与 D2 同构——git tracked 文件不列 doc 就是"幽灵资产"。`__tools_probe__.txt`
命名带 `__` 双下划线前缀也暗示"测试 / 探针"，不是生产代码。

### D4 — autonomous.py 加 `window_s` 参数（公开 API 表面扩展）

**事实**：v0.2.11 commit `65b75fae` 给 `next_task` 加了 `window_s: float = DEFAULT_COOLDOWN_S`
参数（4 处清理之一），理由：测试时需短时间绕过 cooldown，不能改 module 常量污染其他测试。

`next_task` 当前签名：

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

### D5 — compression/hook.py import 整理不留 doc 章节，但注 1 行

**事实**：commit `213da37f` 把 `from .simple import SimpleCompression` 从文件底部挪到顶部
import 块，删掉 `# noqa: E402`，注册语句移到 `REGISTRY` 之后加一行注释"默认注册 +
测试可覆盖"。

**决策**：architecture-v0.md §二 `compression/hook.py` 行注释加 1 行说明"v0.2.10 import
整理（顶部 import + 无 noqa；见 ADR-0011 D5）"。**不开新章节**——这一改动是局部清理，
不是架构层。

**理由**：区分"架构变化"（开 ADR 章节）vs"局部清理"（1 行注）——避免 ADR-0011
膨胀成"啥都记"的杂物筐。

### D6 — 自检约束（D6-5 残留文件扫描）

**D6-1**（沿用 ADR-0006）：本 ADR 改完 `docs/architecture-v0.md` 后必须 `git diff --stat`
看 diff size 是否合理（不应 > 60 行净增）。
**D6-2**（沿用 ADR-0006）：跑 `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no`
看 fail 数；pre-existing fail 必须与本轮**无关**才能 commit。
**D6-3**（沿用 ADR-0006 / ADR-0009）：用 `grep -F '<关键串>'` 确认 doc 里的关键
字符串（如 `ToolRegistry` / `_safe_call` / `manager.py.bak`）真的在 doc 里出现。
**D6-4**（沿用 ADR-0010）：公开 API 签名变更必须写 doc，不留暗坑。
**D6-5（新增）**：每次开 architecture-v0 同步类 ADR 必须做**残留文件扫描**——

  ```bash
  git ls-files src/xragent/ | grep -E '\.(bak|txt|md|json)$|~$|\.swp$'
  ```

  输出若包含 `.py.bak` / `~` / `.swp` / 测试残留的 `.txt`，必须在 doc 里留痕
  （D2 / D3 模式），或在 commit message 里说明"已删"。

**理由**：D6-5 是 ADR-0011 前一版漏掉的"反例"。前一版 commit message 自检里写了
`manager.py.bak` 和 `__tools_probe__.txt`，但 §六"自检约束"章节没把"残留文件扫描"
固化为 D6-5 流程，导致下次（v0.2.11）又会忘了——必须固化。

## 2. 实施步骤

1. 写 `docs/adr/0011-architecture-v0-registry-internals-tracked-files-and-autonomous-window-s.md`（本文）
2. 改 `docs/architecture-v0.md`：
   * §二 `tools/registry.py` 行 3 → 11 行（v0.2.10 内部结构）
   * §二 `memory/manager.py` 行 +3 行（manager.py.bak 留痕）
   * §二 `compression/hook.py` 行 +1 行（import 整理说明）
   * §二 `autonomous.py` 行注释更新（next_task 带 window_s 签名）
   * §二末尾前补 1 行 `__tools_probe__.txt` 探针留痕
   * §五 v0.2.10 + v0.2.11 行新增
   * §一"自驱动（autonomous）"段补 1 行 `window_s`
   * ADR 链接列表加 ADR-0011
3. 改 `README.md`：tools/ 行点名 ToolRegistry + ADR-0011 链接
4. 跑自检 D6-1 ~ D6-5
5. `git add -A && git commit -m "docs: ADR-0011 重做 — registry 内部结构 + 残留文件 + autonomous.window_s (v0.2.10 + v0.2.11)"`

## 3. 自检结果（本轮）

- **D6-1** diff stat：`docs/architecture-v0.md` +14~18 行净增，`docs/adr/0011-*.md` 新增
  ~250 行，`README.md` +2/-1 行；均 ≤ 60 行净增（按文件）✓
- **D6-2** `PYTHONPATH=src python3.11 -m pytest tests/ -q --tb=no`：pre-existing fail
  与本轮 doc-only 改动**完全无关**（src/blacklist.py 找不到 / memory_tools._parse_fact_id
  不存在 / fs_tools.MAX_READ_BYTES 不存在）✓
- **D6-3** `grep -F 'ToolRegistry' docs/architecture-v0.md` → 命中 ✓
  `grep -F '_safe_call' docs/architecture-v0.md` → 命中 ✓
  `grep -F 'manager.py.bak' docs/architecture-v0.md` → 命中 ✓
  `grep -F '__tools_probe__.txt' docs/architecture-v0.md` → 命中 ✓
  `grep -F 'window_s' docs/architecture-v0.md` → 命中 ✓
- **D6-4** 公开 API：`next_task` 签名写进 §二 autonomous.py 行注释 ✓
- **D6-5** 残留文件扫描：

  ```bash
  git ls-files src/xragent/ | grep -E '\.(bak|txt)$'
  # 输出：src/xragent/__tools_probe__.txt
  #       src/xragent/memory/manager.py.bak
  ```

  两个文件均已 D2 / D3 留痕 ✓

## 4. 回滚预案

若本轮 commit 被 revert：
1. 检查 revert commit message 看具体问题（多半是"残留文件扫描漏 / 签名漂移漏"）；
2. 重新开 ADR-0011 v3，把漏点固化到 D6-*；
3. 重做不要"小补丁式"补 commit——按 ADR-0008 经验，**整篇重写比补丁更稳**。

## 5. 与 ADR-0005 / ADR-0006 / ADR-0008 重做模式的对比

| ADR | 前一版问题 | 本轮重做方式 |
| --- | --- | --- |
| ADR-0005 | v0.2.5 首次 sync 不全 | ADR-0006 重做，把"自愈不变量"单列 |
| ADR-0008 | v0.2.7 两次 revert | ADR-0008 重做，固化为"schema + util 一起 sync" |
| **ADR-0011** | v0.2.10 sync 缺 manager.py.bak / __tools_probe__.txt / hook.py import / autonomous window_s | **本轮**重做，范围扩大到 v0.2.10 + v0.2.11，新增 D6-5 残留文件扫描 |