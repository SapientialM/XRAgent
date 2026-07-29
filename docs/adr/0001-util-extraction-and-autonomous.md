# ADR-0001: util/ 公共抽函数 + autonomous 自驱动循环

- 状态：已接受（v0.1.1 增量）
- 日期：2026-07-29
- 决策者：XRAgent（autonomous round），经 supervisor 24h 自愈协议守护

## 背景

出生版（v0.1）仓库里出现两处"该抽出没抽出 / 该有却没有"的债：

1. **重复的 JSONL 解析块**：`autonomous.py::_recent_titles` 和 `evolve/generations.py::list_generations`
   各自手写 read_text → splitlines → strip → safe_json_loads → 过滤 None 共 5+ 行，
   同构代码两份。
2. **没有"没人在也能跑"的循环**：HTTP 父母通道、`--as-supervised`、`--serve` 都依赖人或外部触发；
   supervisor 只能"它崩了拉起它"，不能"它没事做时让它自己找事做"。
   这导致首次 24h 灰度里出现大段空白 round。

## 决策

### D1. 抽出 `src/xragent/util/` 包

按"出现 2+ 次且 ≥5 行"原则抽出共享小工具，不做过度抽象。落地三个模块：

- `util/json_utils.py` — `safe_json_loads` 接受 str/bytes/None，统一错误处理
- `util/jsonl_utils.py` — `iter_jsonl(path)` 生成器，统一 read_text + 行解析 + skip None
- `util/subprocess_utils.py` — subprocess timeout + None-cwd safety + 类型注解

约束：
- 不引入新第三方依赖
- 调用方迁移一次性替换，保持外部 API 不变
- 加 1 个 `tests/test_util.py` 覆盖 safe_json_loads 的三种入参

### D2. 新增 `src/xragent/autonomous.py` 自驱动循环

不是 AGI，是"按一份多元化任务清单 + ReAct + commit"的稳态推进器。

设计要点：
- **任务模板**（8 条，`TASK_TEMPLATES`）：每条都强制 `write_file` 改 `src/`（不接受"只读"task）
- **冷却**：`DEFAULT_COOLDOWN_S = 7200.0`（2h），同 title 不重复
- **留痕**：每次执行 append 到 `memory/queue.jsonl`（不入 git）
- **HTTP 父母通道并行**：自驱动运行时 `POST /message` 仍可插队打断 round
- **commit 策略**：每 round 跑完 `add_all_and_commit`；首条立即 push，后续每 `push_interval_minutes` push
- **退出**：SIGTERM/SIGINT 在本 round 跑完后退出（不粗暴 kill 中间 LLM 调用）

CLI 入口：`--autonomous --interval 30 --max-rounds 0`（0 = 无限）。

## 取舍

### 不做 vs 做了
- ❌ 计划任务系统（cron-like）：引入 scheduler 与当前 ReAct 心跳耦合过紧，先不上
- ❌ autonomous 模式自动跑测试（`scripts/test`）：目前让 agent 自己在 prompt 里写"改完跑 scripts/test"，
  失败由 commit 失败 → git checkout 回滚兜底，不做强制 gate
- ✅ util/ 抽三个：`refactor(util): 抽 jsonl_utils 公共函数` commit `94cac1b4` 已落地
- ✅ autonomous.py：`feat(autonomous): turn-1 self-driver loop` 落地

### 已知的债
- `memory/manager.py.bak`（2852 bytes）是 v5.1 schema 迁移前的备份，下次清理
- `llm/` 包当前空 stub，等 v0.2 多 provider 适配时填充
- autonomous 模式暂不调 SideGit `tag_snapshots`（30s 一轮会刷 2000+ tag/天），只保留 stash 供 rollback

## 影响

- 测试：`PYTHONPATH=src python3.11 -m pytest tests/test_util.py -v` 全绿
- 运行时：autonomous round 平均 8-15s（MockBackend），30s interval 余量充足
- 文档：本 ADR + `docs/architecture-v0.md` §一 §二 §七 同步更新
