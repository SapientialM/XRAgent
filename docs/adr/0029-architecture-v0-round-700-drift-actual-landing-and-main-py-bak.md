# ADR-0029: architecture-v0.md round 700+ drift scan + ADR-0027/0028 actual landing — 6 处 doc drift + main.py.bak 留痕

- **状态**: Accepted（仅 doc 同步；不触碰 src/）
- **日期**: 2026-08-05
- **触发**: 父母 turn 要求"读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失。必须 write_file 改 docs/architecture-v0.md 或加 docs/adr/0001-*.md。改完 commit。"
- **范围**: 本轮独立扫描 `docs/architecture-v0.md` vs `src/xragent/` + `git ls-files` + `git log --all --oneline` + `git rev-parse` + `git log -S`；一次性把所有 drift（真实 + 虚构 + 上轮遗漏）全部 sync 到 doc。
- **前置 ADR**: ADR-0027（commit `59ac89c5` round 688 设计但未落地）+ ADR-0028（round 660 描述但未真改）+ ADR-0024（round 582 引入 3 处虚假设定）+ ADR-0023 D7 / ADR-0025 C1（main.py.bak 早期识别）

## 一、本轮关键发现：ADR-0027 + ADR-0028 自报已落地但实际未落地

ADR-0027（commit `59ac89c5`，round 688）列了 6 处 drift 修复设计（D-A..D-F）+ "一次性全部跑过"的可验证检查；
ADR-0028（round 660 描述稿）同样列了 6 处 drift + top 索引追加。

**但**两个 ADR 都**没有 commit 任何 `docs/architecture-v0.md` 修改**：

```bash
git show --stat 59ac89c5
# ...ure-v0-round-660-drift-fix-fabricated-claims.md | 155 +++++++++++++++++++++
# 1 file changed, 155 insertions(+)
# docs/architecture-v0.md 在两个 ADR ship 后仍然存在所有 6 处 drift:
grep -c web_search_rl docs/architecture-v0.md   # 7
grep -c journal docs/architecture-v0.md         # 12
grep -n SCORE_ docs/architecture-v0.md          # 3 常量描述
ls src/xragent/util/*.py | wc -l                # 8 (但 doc 写 9)
```

## 二、本轮修复范围：6 处 drift（D-A..D-F）+ top 索引追加 + main.py.bak 留痕补登

| id | 位置 | fix |
| --- | --- | --- |
| **D-A** | §一 行 63-65 + §二 行 148 / 154 / 157 + §四 行 224 + §五 行 258 | 删全部 `web_search_rl` 字眼（7 处）；§四 行 224 整段改回真实 web_search **全局** 5min cooldown（commit `aefbc069` v0.5.7，2026-07-29，状态文件 `.run/.web_fetch_state.json`，`RATE_LIMIT_COOLDOWN_S = 300.0`） |
| **D-B** | §四 行 224 + §五 行 258 | 删 `e96001f8` / `96ac1e08` / `b03c98b6` 三个虚构 commit hash；改引真实 `aefbc069` |
| **D-C** | §一 行 64-69 + §二 行 113-122 + §四 行 225-226 + §五 行 258 + 顶部 行 26 | 删 `journal=None` 参数 + `record_done 写盘` + `memory/queue.jsonl` 字眼；§四 行 226 改回 ADR-0011 D4 真实签名（v0.2.11 rng + window_s，无 journal） |
| **D-D** | §二 行 162-163 + §四 行 223 + §五 行 253 | scoring 3→5 常量：补 `SCORE_NO_OBSERVATION` (0.5) + `SCORE_OBSERVATION_FAIL` (0.2) |
| **D-E** | §一 行 63 + §二 行 154 + §五 行 256 | util/ 9→8 模块：去虚构 `web_search_rl` 后回到 8（与 `ls src/xragent/util/*.py \| wc -l` 一致） |
| **D-F** | §三表 行 185 | `web_search` 行补"5min 限流 + diary 留痕"，与 `curl_url` 行 186 对齐（共享同一限流 by `aefbc069`） |
| **top** | 顶部 行 26 + 行 35 后 | (1) 顶部 ADR-0024 索引行去虚构项（web_search_rl / journal / per-host throttle）；(2) 顶部追加 ADR-0027 索引行（已 ship 但未列入）；(3) 顶部追加 ADR-0028 索引行（已 ship 但未列入）；(4) 顶部追加本 ADR-0029 索引行 |
| **new-main.py.bak** | §四 不变量 + §五 v0.13.2 行 | 父 turn 明确要求"main.py.bak 留痕"——把 `src/xragent/main.py.bak`（17935 bytes, untracked, commit `baf810e1d` 同期生成）正式入 §四不变量（留痕条目，不抢 cleanup 决策权）。§五 v0.13.2 旧整行（依赖 3 处虚假设定）删除，新加 v0.13.2 (round 582) 一行只描述 main.py.bak 留痕（替代） |

**§五 v0.13.2 (round 582) 整行删除** —— 整行依赖 3 处虚假设定（web_search_rl + journal + per-host throttle + commit `e96001f8`），删除是本轮最干净方案；web_search 真实限流已在 §四 行 224 改写后的不变量中体现（commit `aefbc069`），autonomous 真实签名已在 §四 行 220 体现（v0.2.11 rng + window_s，ADR-0011 D4）。替代：§五新加 v0.13.2 (round 582) 一行仅描述 main.py.bak 留痕（体现 v0.13.2 round 真实 ship 过的 src/ 痕迹：commit `baf810e1d` 同期生成 main.py.bak，未引入其他有效代码改动）。

## 三、main.py.bak 留痕 — 补 ADR-0028 §四 的"已知遗留"

ADR-0028 §四 最后一段明确说：

> `src/xragent/main.py.bak`（17935 bytes, untracked, ADR-0023 D7 / ADR-0025 C1 已留痕）：**不在本轮处理范围**；§四未列入 `.bak 留痕` 不变量是已知遗留，cleanup 决策属父母 turn，本 ADR 不抢决策权。

**本轮父 turn 明确要求 "main.py.bak 留痕"** —— 所以本轮把它正式入 §四不变量（留痕，不抢 cleanup 决策权）。

新增 §四 不变量行：

> **`src/xragent/main.py.bak` 留痕** | `src/xragent/main.py.bak`（17935 bytes, untracked）commit `baf810e1d`（v0.13.2 doc sync）同期生成；ADR-0023 D7 / ADR-0025 C1 早期识别；清理决策留给父母 turn（本轮仅留痕，不删不改）

新增 §五 v0.13.2 (round 582) 行（替代旧 v0.13.2 整行，描述 main.py.bak 留痕）：

> | v0.13.2 (round 582) | `src/xragent/main.py.bak` 留痕（17935 bytes, untracked, commit `baf810e1d` 同期生成）；清理决策留给父母 turn；ADR-0023 D7 / ADR-0025 C1 早期识别 | ADR-0029 |

## 四、可验证检查（本轮跑过）

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
ls src/xragent/util/*.py | wc -l   # 8

# D-F: web_search 真实限流由 aefbc069 落地（同时作用于 web_search + curl_url）
git show --stat aefbc069
# .gitignore                      |  3 ++
# diary/2026-07-29.md             | 42 ++++++++++
# diary/search-log.md             | 85 +++++++++++++++++++++++
# src/xragent/tools/web_search.py | 70 +++++++++++++++++++

# new: main.py.bak 留痕
ls -la src/xragent/main.py.bak       # -rw-r--r-- 1 cm staff 17935 Aug  4 06:14
git ls-files src/xragent/main.py.bak # 空 (untracked)
git log --all --diff-filter=A -- 'src/xragent/main.py.bak' # 空
# 但 baf810e1d commit 把 main.py 从 17935 字节搬到 main.py.bak 同期生成, 后续 doc sync commit 都未触碰它
```

## 五、不在本轮范围（保持原状）

- ADR-0024 / ADR-0026 / ADR-0027 / ADR-0028 文本本体不动（已 ship，仅引用关系）
- ADR-0024 / ADR-0026 / ADR-0027 / ADR-0028 commit message 不改（已 ship）
- `src/` 不动（本轮纯 doc 同步）
- ROADMAP.md / `docs/agent-capabilities.md` 不动（本轮仅扫 `architecture-v0.md` vs src/）
- `main.py.bak` cleanup 决策留给父母 turn（本轮仅留痕，不删不改）
- `src/xragent/memory/manager.py.bak.5.10`（git tracked, ADR-0024 D6 / ADR-0026 D1 已留痕）：本轮不动

## 六、commit message 设计

```
docs(architecture-v0): round 700+ drift scan + ADR-0027/0028 actual landing + main.py.bak 留痕 (ADR-0029)

应用 ADR-0027 设计的 6 处 doc drift 修复 (D-A..D-F) + 顶部 ADR 索引
追加 ADR-0027 / ADR-0028 / ADR-0029 + 修正 ADR-0024 索引行去虚构项
+ main.py.bak 留痕 (17935 bytes, untracked, commit baf810e1d 同期):

- D-A 删 web_search_rl 字眼 (7 处), web_search 改回真实全局 5min
  cooldown (commit aefbc069 v0.5.7, 状态文件 .run/.web_fetch_state.json,
  RATE_LIMIT_COOLDOWN_S=300.0)
- D-B 删 e96001f8 / 96ac1e08 / b03c98b6 虚构 commit hash, 改引 aefbc069
- D-C 删 autonomous.journal=None + record_done 写盘 + queue.jsonl 字眼
  (12 处); autonomous 真实签名回到 v0.2.11 rng + window_s (ADR-0011 D4)
- D-D scoring 3→5 常量 (补 SCORE_NO_OBSERVATION=0.5 + SCORE_OBSERVATION_FAIL=0.2)
- D-E util/ 9→8 模块 (去虚构 web_search_rl)
- D-F §三表 web_search 补"5min 限流 + diary 留痕" (与 curl_url 对齐)
- top 顶部 ADR-0024 索引行去虚构项 + 追加 ADR-0027 / ADR-0028 / ADR-0029
- new §四 + §五 加 main.py.bak 留痕 (17935 bytes untracked, ADR-0023 D7 / ADR-0025 C1
  早期识别, cleanup 决策留给父母 turn); §五 v0.13.2 整行删除 (依赖 3 处虚假设定)
  + 新加 v0.13.2 一行仅描述 main.py.bak 留痕 (替代)

纯 doc 同步, src_diff=false.
```

## 七、本轮是否需新落地 src/ 变更？

**否**。所有漂移都是 doc ↔ 真实代码不一致；修复方式是改 doc + 写 ADR-0029 记录 + commit。