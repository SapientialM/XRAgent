# XRAgent · 息壤

> 一抔能自生长的土。自我学习、自我迭代、自我替代的 LLM Agent。

[![status](https://img.shields.io/badge/status-v0.1%20birth-green)]()
[![python](https://img.shields.io/badge/python-3.11+-blue)]()
[![license](https://img.shields.io/badge/license-MIT-blue)]()

XRAgent（息壤）是一个能自我学习、自我迭代的 LLM Agent 框架。名字取自《山海经》注："息壤者，土之能自生长者"。本仓库是它的**出生版（v0.1）**：跑通 ReAct 循环、五大核心、24h 自愈、金蝉脱壳闭环与 HTTP 父母通道。

## ✨ 特性

- **ReAct 循环** — 推理 → 行动 → 观察 → 推理，标准 agent 范式
- **五大核心** — 梦想（AGENTS.md 强 prepend）/ 父母（stdin + HITL + HTTP）/ 生活（仓库级路径围栏 + binary 黑名单）/ 记忆（Git + SQLite + diary 三层）/ 成长（commit → push → py_compile → supervisor 切换）
- **9 工具** — read_file / list_dir / write_file / run_cmd / git_commit / git_push / memory_save / diary_write / propose_self_replace / terminate
- **24h 自愈** — `watchdog/supervisor.py` 父进程监控 `runtime_state.json::heartbeat_ts`；超时 → 自动 kill 子 → 自动重启；连续失败 5 次停机
- **极简 HTTP 父母通道** — `POST /message` 喂消息，`GET /last-answer` 取最新回答，`GET /health` 看心跳
- **多 LLM provider** — OpenAI / DeepSeek / GLM / Mock，OpenAI-compatible 协议切换
- **路径围栏** — 所有写操作 `resolve().is_relative_to(repo_root)`；AGENTS.md / .env / .git / runtime_state.json / diary/turns/ 黑名单

## 🚀 快速开始

### 前置条件

- Python 3.11+
- （可选）至少一个 LLM API Key（OpenAI / DeepSeek / GLM 任一）

### 安装依赖

```bash
cd XRAgent
python3.11 -m pip install -r requirements.txt
# 或者：
python3.11 -m pip install pydantic pydantic-settings langchain-core langchain-community openai pytest pytest-asyncio
```

### 不带 LLM 跑通闭环（mock backend）

```bash
PYTHONPATH=src python3.11 -m xragent.main --smoke
```

输出示例：

```
[smoke] turn_id=20260728-004038-733
[smoke] answer=我是 XRAgent，息壤。今天是我出生的第一天 (mock)。
[smoke] wall_ms=1 tokens_in=0
```

### 交互式

```bash
PYTHONPATH=src python3.11 -m xragent.main
# 输入自然语言对话；/tools /memory /diary /snapshot /quit
```

### 启动 HTTP 父母通道

```bash
PYTHONPATH=src python3.11 -m xragent.main --serve --port 10086
# 然后：
curl -X POST http://127.0.0.1:10086/message -H "Content-Type: application/json" -d '{"text":"自我介绍一下"}'
curl http://127.0.0.1:10086/last-answer
curl http://127.0.0.1:10086/health
```

### 启动 24h supervisor

```bash
PYTHONPATH=src python3.11 -m xragent.watchdog.supervisor
# supervisor 会拉起子 Agent，监控心跳，崩溃自动重启
```

## ⚙️ 配置

`.env`（复制 `.env.example` 改）：

```bash
XRAGENT_LLM_PROVIDER=openai           # openai / deepseek / glm / mock
XRAGENT_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1

XRAGENT_EVOLUTION_ENABLED=true        # false = 冻结蜕皮 + terminate
XRAGENT_HTTP_PORT=10086
XRAGENT_HTTP_TOKEN=                   # 空 = 不鉴权；非空 = Bearer token

XRAGENT_HEARTBEAT_INTERVAL_S=10
XRAGENT_HEARTBEAT_TIMEOUT_S=60
XRAGENT_RESTART_MAX_FAILURES=5
```

## 🧱 架构（v0.1）

```
XRAgent/
├── AGENTS.md                       # 梦想：最高指导原则（Agent 不可改）
├── docs/architecture-v0.md         # 完整方案 v0.2
├── diary/                          # 日记（人类可读 + 系统结构化）
│   ├── YYYY-MM-DD.md
│   └── turns/<id>.jsonl
├── memory/long_term/facts.db       # SQLite 长期事实
├── runtime_state.json              # 心跳 / 世代谱 / 终止开关
├── src/xragent/
│   ├── core/      (dream / backend / react_loop / turn)
│   ├── tools/     (registry + 9 工具 + blacklist)
│   ├── memory/    (manager)
│   ├── snapshot/  (side_git)
│   ├── hitl/      (gate)
│   ├── evolve/    (generations / metamorphosis)
│   ├── compression/ (simple / hook)
│   ├── watchdog/  (supervisor / runtime_state)
│   ├── config/    (settings)
│   └── main.py    (CLI)
└── tests/         (32 单测 + 5 e2e = 37 用例)
```

## 🛠 CLI 子命令

| 命令 | 说明 |
| --- | --- |
| `--smoke` | 跑通一次 mock 闭环 |
| `--once "<text>"` | 处理一条用户输入后退出 |
| `--serve` | 启动 HTTP 父母通道 + ReAct 后台循环 |
| `--as-supervised` | 被 supervisor 拉起，定期写心跳 |
| `--freeze` | 禁用 `propose_self_replace` / `terminate` |
| (默认) | 交互式 ReAct（stdin TTY）或纯 HTTP 队列 |

## 🔒 五大核心落地

| 核心 | 实现 | 文件 |
| --- | --- | --- |
| 梦想 | `AGENTS.md` 强 prepend 到 system prompt；工具黑名单禁写 | `core/dream.py`, `tools/blacklist.py` |
| 父母 | stdin + HITL Gate 三态决策（approve/reject/edit）+ HTTP /message /approve | `hitl/gate.py`, `http_server.py` |
| 生活 | `PathSandbox` 仓库根围栏；`AGENTS.md` `.env` `.git` `runtime_state.json` `diary/turns/` 黑名单 | `tools/blacklist.py` |
| 记忆 | Git + `memory/long_term/facts.db`（SQLite append-only）+ `diary/YYYY-MM-DD.md` + `diary/turns/<id>.jsonl` + 短期 messages | `memory/manager.py`, `core/turn.py`, `snapshot/side_git.py` |
| 成长 | `propose_self_replace`：commit → push → py_compile → 世代谱 → 通知 supervisor 切换 | `evolve/metamorphosis.py`, `evolve/generations.py` |

## 📝 24h 自愈协议

```
父进程 (supervisor)
   │
   ├─ spawn 子进程 (main --as-supervised)
   │      │
   │      ├─ 每轮 ReAct 后调 on_heartbeat() 写 runtime_state.json::heartbeat_ts
   │      └─ 阻塞 stdin / 消费 HTTP /message 队列
   │
   ├─ 监控循环（每 heartbeat_interval_s 秒）
   │      ├─ 子进程退出 rc=0 且 restart_suppressed → 退出
   │      ├─ 子进程退出 rc!=0 → 失败计数 +1，重启
   │      └─ 心跳超时 → SIGTERM 子进程，重启
   │
   └─ 连续失败 restart_max_failures 次 → 停机
```

## 🚦 验证

```bash
PYTHONPATH=src python3.11 -m pytest tests/ -v
# 32 单测 + 5 e2e = 37 用例
```

## 📚 文档

- [`docs/architecture-v0.md`](docs/architecture-v0.md) — 完整方案 v0.2（路径围栏 / HITL / 金蝉脱壳 / 路线图）
- [`AGENTS.md`](AGENTS.md) — 梦想（最高指导原则）
- [`diary/2026-07-28.md`](diary/2026-07-28.md) — 出生纪事

## 🗺 路线

| 版本 | 目标 | 状态 |
| --- | --- | --- |
| v0.1 | 出生：ReAct + 9 工具 + HITL + Side-Git + Dream + Diary + 蜕皮 + HTTP 父母 | ✅ |
| v0.2 | 多 provider 适配 4 家 LLM；断网 fallback | planned |
| v0.3 | 长期记忆 SQLite + recall 工具可用 | planned |
| v0.4 | 评分基线（每个 turn 加 score） | planned |
| v0.5 | 金蝉脱壳强化（自动 push + 编译 + 切换） | partial（v0.1 已含基础） |
| v0.6 | 双分支雏形（Agent A / Agent B 用 git worktree 隔离） | planned |
| v0.7 | 自动评分员（pytest + ruff + mypy） | planned |
| v0.8 | HIL 升级：持续 stdin 流 + interrupt 强制停 | planned |
| v0.9 | LangChain 评估（决定是否换原生 SDK） | planned |
| v1.0 | 稳定双 Agent（A/B 分支 + 角色互换 + 记忆连续） | planned |

## ⚖️ License

Apache License
