# ADR-0028: architecture-v0.md round 660+ drift fix 实际落地 — ADR-0027 设计的 6 处 doc 修复生效

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-05
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。必须 write_file 改 docs/architecture-v0.md 或加 docs/adr/0001-*.md。改完 commit。"（round 660+ drift scan 落地）
- **范围**: 本轮一次性把 ADR-0027（round 660 drift fix 设计）设计的 6 处 doc 修复**实际**落到 `docs/architecture-v0.md`，并修正 ADR-0024 索引行的虚假设定 + 顶部 ADR 索引列表追加 ADR-0027 + ADR-0028 两行。
- **前置 ADR**: ADR-0027（round 660 设计稿，本轮实际落地）
- **本轮不涉及**: ADR-0024 / ADR-0026 commit message（已 ship） + ADR-0027 / ADR-0024 / ADR-0026 文本本体 + 任何 src/

## 一、关键背景：ADR-0027 自报落地但实际未落地

ADR-0027（commit `59ac89c5`，round 688，2026-08-04 01:24:14 +0800）声称已"全部 sync 到 doc"，列了 6 处 drift 修复（D-A web_search_rl 删除 / D-B e96001f8 删除 / D-C journal 删除 / D-D scoring 3→5 常量 / D-E util/ 9→8 模块 / D-F §三表 web_search 补"5min 限流"）+ "顶部追加 ADR-0027 索引行"。

**但** ADR-0027 只 commit 了 `docs/adr/0027-...md` 一个新文件（+155 行），**没有 commit 任何 `docs/architecture-v0.md` 修改**：

```bash
git show --stat 59ac89c5
# ...ure-v0-round-660-drift-fix-fabricated-claims.md | 155 +++++++++++++++++++++
# 1 file changed, 155 insertions(+)
```

结果：`docs/architecture-v0.md` 在 ADR-0027 commit 后**仍然存在所有 6 处 drift**：
- `grep -c web_search_rl docs/architecture-v0.md` = **7**（仍在）
- `grep -c journal docs/architecture-v0.md` = **12**（仍在）
- `grep -n SCORE_ docs/architecture-v0.md` 仍是 3 常量描述（仍在）
- 顶部索引最后一条仍是 ADR-0026（ADR-0027 + ADR-0028 没列入）

本轮 fix 范围 = 把 ADR-0027 的设计**实际应用**到 `docs/architecture-v0.md`。

## 二、本轮实际落地 6 处 drift（D-A 到 D-F）+ 顶部索引修正

| id | 位置（旧行号） | fix |
| --- | --- | --- |
| **D-A** | §一 行 64-65 + §二 行 148 / 154 / 157 + §四 行 224 + §五 行 258 | 删全部 `web_search_rl` 字眼；§四行 224 整段改回真实 web_search **全局** 5min cooldown（commit `aefbc069` v0.5.7，2026-07-29，状态文件 `.run/.web_fetch_state.json`，`RATE_LIMIT_COOLDOWN_S = 300.0`） |
| **D-B** | §四 行 224 + §五 行 258 | 删 `e96001f8` / `96ac1e08` / `b03c98b6` 三个虚构 commit hash；改引真实 `aefbc069` |
| **D-C** | §一 行 45-49 + §二 行 114-122 + §四 行 225-226 + §五 行 258 + 顶部 行 26 | 删 `journal=None` 参数 + `record_done 写盘` + `memory/queue.jsonl` 字眼；§四行 226 改回 ADR-0011 D4 真实签名（v0.2.11 rng + window_s，无 journal） |
| **D-D** | §二 行 162-163 + §四 行 223 + §五 行 253 | scoring 3→5 常量：补 `SCORE_NO_OBSERVATION` (0.5) + `SCORE_OBSERVATION_FAIL` (0.2) |
| **D-E** | §一 行 63-65 + §二 行 154 + §五 行 256 | util/ 9→8 模块：去虚构 `web_search_rl` 后回到 8（与 `ls src/xragent/util/*.py \| wc -l` 一致） |
| **D-F** | §三表 行 185 | `web_search` 补"5min 限流 + diary 留痕"，与 `curl_url` 行 186 对齐（共享同一限流 by `aefbc069`） |
| **top** | 顶部 行 26 + 行 35 后 | (1) 顶部 ADR-0024 索引行去虚构项（web_search_rl / journal / per-host throttle）；(2) 顶部追加 ADR-0027 索引行（已 ship 但未列入）；(3) 顶部追加本 ADR-0028 索引行 |

## 三、可验证检查（与 ADR-0027 §四 一致，本轮跑过）

```bash
# D-A: util/web_search_rl.py 0 hits
ls src/xragent/util/web_search_rl.py   # not found
git log --all --diff-filter=A -- 'src/xragent/util/web_search_rl.py'   # 空
git log --all -S "Throttle" -- src/   # 空

# D-B: 3 个 commit 全 fatal
git rev-parse 96ac1e08   # fatal: unknown revision
git rev-parse e96001f8   # fatal: unknown revision
git rev-parse b03c98b6   # fatal: unknown revision

# D-C: autonomous.py 无 journal 参数 + 无 queue.jsonl 写盘
grep -n "journal" src/xragent/autonomous.py   # 仅命中 memory/queue.jsonl 路径常量（与 cooldown key 同路径，非写盘逻辑）
ls src/xragent/memory/queue.jsonl   # not found

# D-D: scoring 5 常量
grep -n "^SCORE_" src/xragent/scoring/score.py
# 行 57: SCORE_RANGE: Final[tuple[float, float]] = (0.0, 1.0)
# 行 60: SCORE_ERROR: Final[float] = 0.0
# 行 63: SCORE_OK_BASE: Final[float] = 0.7
# 行 66: SCORE_NO_OBSERVATION: Final[float] = 0.5
# 行 69: SCORE_OBSERVATION_FAIL: Final[float] = 0.2

# D-E: util/ 8 模块
ls src/xragent/util/*.py | wc -l   # 8 (json_utils / jsonl_utils / subprocess_utils / diary_archive / git_helpers / heartbeat / http_parents / print_guard)

# D-F: web_search 真实限流由 aefbc069 落地（同时作用于 web_search + curl_url）
git show --stat aefbc069
# .gitignore                      |  3 ++
# diary/2026-07-29.md             | 42 ++++++++++
# diary/search-log.md             | 85 +++++++++++++++++++++++
# src/xragent/tools/web_search.py | 70 +++++++++++++++++++
```

## 四、不在本轮范围（与 ADR-0027 §五 一致）

- ADR-0024 / ADR-0026 / ADR-0027 文本本体不动（已 ship）
- ADR-0024 / ADR-0026 / ADR-0027 commit message 不改（已 ship）
- `src/` 不动（本轮纯 doc 同步）
- `src/xragent/main.py.bak`（17935 bytes, untracked, ADR-0023 D7 / ADR-0025 C1 已留痕）：**不在本轮处理范围**；§四未列入 `.bak 留痕` 不变量是已知遗留，cleanup 决策属父母 turn，本 ADR 不抢决策权。
- `src/xragent/memory/manager.py.bak.5.10`（git tracked, ADR-0024 D6 / ADR-0026 D1 已留痕）：本轮不动。
- ROADMAP.md / `docs/agent-capabilities.md` 不动（本轮仅扫 `architecture-v0.md` vs src/）

## 五、commit message 设计

```
docs(architecture-v0): round 660+ drift fix 实际落地 (ADR-0028)

应用 ADR-0027 设计的 6 处 doc drift 修复 (D-A..D-F) + 顶部 ADR 索引
追加 ADR-0027 / ADR-0028 + 修正 ADR-0024 索引行去虚构项:

- D-A 删 web_search_rl 字眼 (7 处), web_search 改回真实全局 5min
  cooldown (commit aefbc069 v0.5.7, 状态文件 .run/.web_fetch_state.json)
- D-B 删 e96001f8 / 96ac1e08 / b03c98b6 虚构 commit hash
- D-C 删 autonomous.journal=None + record_done 写盘 + queue.jsonl 字眼
  (4 处); autonomous 真实签名回到 v0.2.11 rng + window_s (ADR-0011 D4)
- D-D scoring 3→5 常量 (补 SCORE_NO_OBSERVATION=0.5 + SCORE_OBSERVATION_FAIL=0.2)
- D-E util/ 9→8 模块 (去虚构 web_search_rl)
- D-F §三表 web_search 补"5min 限流 + diary 留痕"
- top 顶部 ADR-0024 索引行去虚构项 + 追加 ADR-0027 / ADR-0028

纯 doc 同步, src_diff=false.
```

## 六、本轮是否需新落地 src/ 变更？

**否**。所有漂移都是 doc ↔ 真实代码不一致；修复方式是改 doc + 写 ADR-0028 记录。