# ADR-0021: architecture-v0.md round 325+ close-out — ADR-0020 round 235 落地的 4 处 doc 修复全部反弹重做 + scoring/ 目录真正消失（超出 ADR-0020 D2 范围）

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-04
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
- **范围**: 仅 doc 同步；ADR-0020 D3（main.py 接入 print_guard）/ D4（tools/registry.py docstring 补 2 工具）的 code drift 仍留给后续 round 显式 turn
- **前置**: ADR-0017、ADR-0018（v0.10 round 215+ close-out）、ADR-0019（v0.11+ round 231 age_cleanup）、**ADR-0020（round 235 close-out — ADR-0018 D1/D2 实际落地；本 ADR-0021 是 ADR-0020 跨 90 round 二次落地）**

## 一、扫描方法

对照 `docs/architecture-v0.md` 与 `src/xragent/` 实际树，核对：

1. ADR-0020 round 235 落地（推测 hash 在 `e9f55871` 附近，标题"docs(arch): ADR-0020 + sync architecture-v0.md"）的 5 处 doc 修复是否仍生效。
2. round 235 → round 325+（跨 90 round）的 13+ 轮 close-out 是否再次让 doc 漂回旧状态。
3. **新发现**（超出 ADR-0020 D2 范围）：`src/xragent/scoring/` 目录是否仍"完全空"，还是连目录本身都消失了。

## 二、drift 清单

### D1 — ADR-0020 round 235 落地的 4 处 doc 修复**全部反弹**（**最大 drift**，跨 90 round 二次失真）

- **ADR-0020** 描述的修复方案（§五变更范围表的 5 行）：顶部 ADR 索引加 ADR-0020 条目 + §一 7→8 + §二 7→8 + §二/§四 scoring/ 措辞改"完全空" + §五行加 v0.10 行。
- **本轮（round 325+）实测**（`grep -n "print_guard\|8 个模块\|7 个模块\|v0.10\|0020" docs/architecture-v0.md` + `sed -n '50,58p'` + `sed -n '128,140p'` + `sed -n '195,205p'`）：
  - 顶部 ADR 索引（行 19-20）：只有 ADR-0019，无 ADR-0020 引用行 —— **反弹**
  - §一行 52：「当前 **7 个模块**：`json_utils` / `jsonl_utils` / `subprocess_utils` / `diary_archive` / `git_helpers` / `heartbeat` / `http_parents`」 — 仍是 7 个名字（`print_guard.py` 漏列）—— **反弹**
  - §二行 131：`util/                      # 7 个模块：json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents` — 仍是 7 个名字 —— **反弹**
  - §二行 137-139：「`scoring/` 占位包（v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；...）」 — 仍是 v0.13.1 旧表述 —— **反弹**
  - §四行 199：「`src/xragent/scoring/` v0.13.1 状态：持续仅 `__pycache__/`，缺 `__init__.py`，未 git tracked；...」 — 仍是 v0.13.1 旧表述 —— **反弹**
  - §五行：`grep "v0.10"` 只匹配顶部 ADR-0018 索引行（行 20），**§五版本对照表本身没有 v0.10 行** —— **反弹**
- **drift 性质**：ADR-0020 Accepted 时声称"doc sync 已 ship"，但从 round 235 → round 325+（跨 90 round）经历了 13+ 轮 close-out（`02d33634` round 283+ / `b5153a4e` round 280+ / `75a1c0ab` round 279+ / `7994ff13` round 279 / 之前还有 round 278/277/.../236 等），每轮都标 `src/ 0 diff`，但从没人回头复核 doc 是否又漂回去。**这是 ADR-0020 修复方案本身的脆弱性——单点 doc 修改在 close-out 链路上反复失真**。
- **修复**（本轮实际执行）：详见 §五变更范围表。

### D2 — scoring/ 目录**整个消失**（超 ADR-0020 D2 "目录存在但完全空"范围，round 325+ 进一步清理触发）

- **ADR-0020 D2** 描述的修复方案：`scoring/` "目录存在但完全空（含 `__pycache__/` 已无残留）"。
- **本轮实测**（`ls src/xragent/scoring/`）：`No such file or directory` —— **整个目录消失**，对比 `ls src/xragent/llm/` 仍有 `__init__.py` + `__pycache__/`，证明 scoring/ 不是"被清空"，而是"被某次 cleanup / git rm / 目录清理动作彻底删除"。
- **drift 性质**：从 round 235 → round 325+ 期间（跨 90 round）的 close-out 链路上，scoring/ 目录被某次清理（最可能是 build artifact cleanup / git clean -fd / 手动删除）整个移除。**这超出 ADR-0020 D2 修复方案描述**——D2 只覆盖了"__pycache__/ 也没了"的情形，未覆盖"目录本身也没了"。
- **诚实修复策略**（本轮实际执行）：
  - §二行 137-139 scoring/ 块名从 `scoring/                   # 占位包（v0.13.1 状态：持续仅 __pycache__/...）` 改为 `[scoring/ 不存在]          # 占位包生命周期：v0.3.1 登记 → v0.13.1 二次清空 → round 325+ 自某次清理起**目录整个消失**`；
  - §四行 199 不变量名从 `scoring/ 目录占位` 改为 `scoring/ 占位包生命周期` + 内容描述完整演进链（含 round 325+ "目录整个消失"）；
  - **决策仍为**：不主动重建 `__init__.py`、不主动 mkdir、不主动 git add 空目录；ROADMAP 未把 scoring/ 提为 blocked，重建/废弃决策留给后续 round。
- **诚实留痕**：本 ADR-0021 显式标注"超出 ADR-0020 D2 修复范围"，让未来读 doc 的人知道 round 325+ 二次发现的事实。

### D3 — ADR-0020 D3（util/print_guard helper 未被 main.py 接入）**仍未修**（沿袭 ADR-0020 决策留给后续 round）

- **doc 状态**：本轮 §五 v0.10 行追加的 print_guard 子行**会显式标注**「main.py 实际未接入 — 见 ADR-0018 D3 / ADR-0020 D3 / ADR-0021 D3」，让 doc 自身承认这件事存在。
- **code 状态**（`grep -rn "print_guard" src/`）：main.py 与 `src/` 其他模块**仍未导入 print_guard**；仅 `tests/test_print_guard.py` 使用。`src/xragent/main.py` 仍有 inline `except Exception as e: print(f"[autonomous] ... failed: ...", flush=True)` 4+ 处（在 autonomous 循环的 push / commit / task gen / parent reply 路径）。
- **决策**：**本轮仍不接入**。沿袭 ADR-0018 D3 / ADR-0020 D3 决策（父母本轮 turn 只要求 doc 同步，未授权 src/ 改动；接入需逐处判断 fallback 语义属业务策略决策）。本 ADR-0021 仅在 doc §五 v0.10 行**显式标注**"main.py 实际未接入"，并把"main.py 4+ 处待接入清单"原样从 ADR-0020 D3 抄到本 ADR D3，留给后续 round 显式 turn。
- 接入点草案（沿袭 ADR-0020 D3 / 本 ADR-0021 D3）：
  - main.py:359（push 失败）→ fallback: 跳过 `last_push_ts = now`
  - main.py:368（commit 失败）→ fallback: 跳过 commit-only 副作用但仍 `record_done`
  - main.py:378 + 后续（task gen 失败）→ fallback: sleep 60s + continue
  - main.py:275 + 279（非 `cmd_autonomous` 内，`cmd_serve` 或 main entry）→ 是否接入需逐处判断语义

### D4 — tools/registry.py docstring 漏列 v0.3.1 的 2 个工具（沿袭 ADR-0017 D2 / ADR-0018 D4 / ADR-0020 D4，本轮仍未修）

- **doc 状态**：architecture-v0.md §三已记 19 个工具，**doc 自身 OK**。
- **in-source 状态**（`tools/registry.py` docstring）：低风险组还停留在 v0.2.6 的 8 个，漏了 `memory_recall_by_title` + `memory_update_title`（v0.3.1 +2）。
- **决策**：**本轮仍不修 in-source docstring**。沿袭 ADR-0017 D2 / ADR-0018 D4 / ADR-0020 D4 决策（父母本轮 turn 限定 doc 范围，未授权 src/ 改动）。留给下一轮显式 docstring sync turn。

### D5 — §一 / §二 util/ 列表顺序与 `util/__init__.py` 不 re-export 一致性（未变项确认）

- **doc 状态**：§一 + §二 util/ 8 个模块的列表顺序：`json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents / print_guard`，与 `src/xragent/util/` 实际 `ls` 顺序一致；`util/__init__.py` 不 re-export 仍正确（仅模块级 docstring + `from __future__ import annotations`）。
- **本轮修复**：仅追加 print_guard 到末尾，不重排前面 7 个的顺序（保持最小改动原则）。

## 三、ADR-0020 D1-D5 状态（已 + 未）

- **D1** ADR-0020 round 235 落地的 4 处 doc 修复**全部反弹** → 本 ADR-0021 D1 二次落地（重做）
- **D2** scoring/ "目录存在但完全空" → **新发现**：目录整个消失，本 ADR-0021 D2 二次扩展（超出原 D2 范围）
- **D3** main.py print_guard 接入点 → 仍未修，沿袭决策
- **D4** tools/registry.py docstring 补 2 工具 → 仍未修，沿袭决策
- **D5** util/ 列表顺序一致性 → 未变项确认 OK

## 四、未变项（核对一致）

- §一五大核心的实现位置全部仍在（`core/dream.py` / `hitl/gate.py` / `tools/blacklist.py` / `memory/manager.py` + `snapshot/*` / `evolve/*` + `autonomous.py` + `watchdog/supervisor.py`）。
- §二模块清单除 util/ 7→8 + scoring/ 块名改 `[scoring/ 不存在]` + 内容改"目录整个消失"外其他条目逐一比对：`tools/` 9 个 .py、`watchdog/` 2 个、`core/` 4 个、`snapshot/` 5 个（含 age_cleanup）、`evolve/` 2 个、`compression/` 2 个、`util/` 8 个（本 ADR 修复后）、`hitl/` 1 个、`llm/` 仍仅 `__init__.py` —— 全部对得上。
- §三工具表 19 个与 `build_default_registry()` 注册一致；evolution_enabled=false 时剩 17 个也一致。
- §四关键不变量的 13 条引用全部存在（write_blacklist / cmd_blacklist / HitlGate / evolution_enabled / snapshot_cleanup / cleanup_old_snapshots / count_cleanup / _tag_index / push_interval_minutes / runtime_state.json / heartbeat_timeout_s / read_file.original_size / tools/registry.run 流程契约）。
- `memory/manager.py::SCHEMA_VERSION = 58` 未 bump（已知遗留，5.9 是 DDL-only 二次回填，与 ADR-0017 D3 / ADR-0020 一致）。
- ADR-0019 全部 D1-D5 已落地（与 ADR-0020 一致）。
- ADR-0020 描述的修复方案除"已反弹"外，其余 drift 性质描述与本轮实测一致。

## 五、变更范围（diff stat）

```
docs/adr/0021-architecture-v0-round-325-adr-0020-redo-and-scoring-truly-gone.md | +N NN
docs/architecture-v0.md                                                     | +M MM
```

具体改动：

| 文件 | 改动 |
| --- | --- |
| `docs/adr/0021-*.md`（new） | 本 ADR |
| `docs/architecture-v0.md` 顶部 ADR 索引行 20-21 | 追加 ADR-0020 + ADR-0021 引用行；让两次修复都有显式索引 |
| `docs/architecture-v0.md` §一 util/ 列表（行 52-54） | 7 → 8 modules + 加 print_guard.py 注释 + 引用 ADR-0018 / 0020 / 0021 |
| `docs/architecture-v0.md` §一 util/ 注释（行 56-58） | heartbeat / http_parents 句后追加 print_guard.py 注释：把 main.py 4 段 `try/except Exception + print failed` 模板收敛到 helper；guard 包"fn 出错→打 tag + 返 fallback"，失败不污染冷却时钟 |
| `docs/architecture-v0.md` §二 util/ 子条目（行 131-132） | 7 → 8 modules + 加 print_guard.py 注释行 + 引用 ADR-0018 / 0020 / 0021 |
| `docs/architecture-v0.md` §二 scoring/ 块（行 137-139） | 块名 `scoring/` → `[scoring/ 不存在]`；内容改完整演进链（含 round 325+ "目录整个消失"），引用 ADR-0012 / 0013 / 0017 / 0018 / 0020 / 0021 |
| `docs/architecture-v0.md` §四 scoring/ 不变量行（行 199） | 名 `scoring/ 目录占位` → `scoring/ 占位包生命周期`；内容改完整演进链（含 round 325+ "目录整个消失"） |
| `docs/architecture-v0.md` §五版本对照表 v0.11+ (round 231) 行（行 225）之前插入 | 追加新行 v0.10 (round 203 + 215+ close-out)：「util/print_guard.py 抽取（main.py try/except Exception + print failed 模板抽 helper；commit `605ed28e` round 203；tests/test_print_guard.py 14 cases 全过锁契约；**main.py 实际未接入 — 见 ADR-0018 D3 / ADR-0020 D3 / ADR-0021 D3**）」 |

`src/xragent/main.py` 不动（D3 决策：留给后续 round 显式 turn）。
`src/xragent/tools/registry.py` docstring 不动（D4 决策：留给后续 round）。
`src/xragent/scoring/` 不动（D2 决策：不重建 `__init__.py`、不 mkdir、不 git add 空目录；ROADMAP 未把 scoring/ 提为 blocked）。
无 schema 变更、无行为变更、无测试破坏面。

## 六、教训（留给未来 close-out 链路）

ADR-0020 落地后跨 90 round 13+ 轮 close-out 都标 `src/ 0 diff`，但没人回头复核 doc 是否漂回原状态。这暴露出 3 件事：

1. **ADR 文本 ≠ 实际修复**：ADR Accepted 不等于 doc 实际被修复。close-out 链路上需要有人显式复核 ADR §五变更范围表的"diff stat"是否真的反映在工作树里。
2. **单点 doc 修改脆弱**：close-out 链路上反复回滚/重放 git history，单点手改容易被吞。**建议**：未来 doc sync 类 ADR 落地后，在 README 或 ROADMAP 顶部加显式索引（如本轮 ADR-0021 顶部索引），让后续 close-out 链路能"看见"这个 ADR 仍需被维护。
3. **scoring/ 演进是 doc 漂移的活标本**：v0.3.1 登记 → v0.13.1 二次清空 → round 325+ 整个消失，三次状态都被 doc 反复错描述。**建议**：未来类似"占位 / 弃用 / 待定"包，建议在 `docs/adr/` 单独建一个 `STATUS.md` 跟踪表，而不是写在 architecture-v0.md 里——后者 225 行单文件被 close-out 链路反复触碰，状态易丢。