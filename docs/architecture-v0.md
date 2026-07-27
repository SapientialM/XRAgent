# XRAgent 架构摘要（v0.1 出生版）

> 完整方案在多次迭代中展开；此文档是 v0.1 出生时的快速地图。

## 一、五大核心

| 核心 | 实现位置 |
| --- | --- |
| 梦想 | `AGENTS.md` + `core/dream.py` |
| 父母 | `hitl/gate.py` + `http_server.py` |
| 生活 | `tools/blacklist.py`（仓库根路径围栏 + 黑名单） |
| 记忆 | `memory/manager.py` + `core/turn.py` + `snapshot/side_git.py` |
| 成长 | `evolve/metamorphosis.py` + `evolve/generations.py` |

## 二、模块清单

```
src/xragent/
├── config/settings.py         # pydantic-settings
├── core/dream.py              # AGENTS.md 加载
├── core/backend.py            # BackendProtocol + Mock + LangChain
├── core/turn.py               # TurnRecord + TraceRecorder
├── core/react_loop.py         # ReAct 主循环
├── memory/manager.py          # SQLite 长期事实
├── compression/simple.py      # 最简压缩
├── compression/hook.py        # 压缩策略注册表
├── snapshot/side_git.py       # 每个 turn snapshot
├── hitl/gate.py               # 三态决策
├── tools/blacklist.py         # PathSandbox + binary 黑名单
├── tools/registry.py          # 9 工具注册
├── tools/fs_tools.py
├── tools/exec_tools.py
├── tools/git_tools.py
├── tools/memory_tools.py
├── tools/diary_tools.py
├── tools/evolve_tools.py
├── evolve/generations.py      # 世代谱
├── evolve/metamorphosis.py    # 金蝉脱壳
├── watchdog/runtime_state.py
├── watchdog/supervisor.py     # 24h 守护
├── http_server.py             # 父母通道
└── main.py                    # CLI 入口
```

## 三、关键不变量

1. **AGENTS.md 不可写**：黑名单 + tools/blacklist 强制
2. **路径围栏**：`PathSandbox.assert_writable()` 强制 resolve 后在 repo_root 之下
3. **二进制黑名单**：`assert_command_allowed()` 拒绝 curl/wget/ssh/nc 等
4. **HITL 门**：高危工具（write_file / run_cmd / git_commit / git_push / propose_self_replace / terminate）走审批
5. **同记忆**：facts.db + diary/turns/ + generations.jsonl 在仓库根，跨重启保留
6. **SideGit 不动源代码**：snapshot 只 stash tracked changes（v0.1 修复后）

## 四、24h 自愈协议

```
supervisor (watchdog/supervisor.py)
    ├── spawn child: python -m xragent.main --as-supervised
    ├── 每 heartbeat_interval_s 检查 runtime_state.json::heartbeat_ts
    ├── 超时（heartbeat_timeout_s）→ SIGTERM child → 重启
    ├── child rc != 0 → 失败计数 +1 → 重启（间隔指数退避）
    ├── restart_suppressed → 退出
    └── restart_count >= restart_max_failures → 停机报警
```

## 五、HTTP 父母通道

```
GET  /health          → {pid, heartbeat_ts, restart_count, metamorphosis_pending}
POST /message {text}  → enqueue 到主循环 input_queue
GET  /last-answer     → {answer, ts}
POST /approve {id,...}→ 回复被挂起的审批（用于 HITL HTTP 通道）
```

## 六、演进路线

- v0.1 (current)：出生 — ReAct + 9 工具 + HITL + Side-Git + Dream + Diary + 蜕皮 + HTTP 父母
- v0.2：多 LLM provider 适配（OpenAI / DeepSeek / GLM / Mock）
- v0.3：长期记忆强化（recall 工具 + 摘要压缩 hook 启用）
- v0.4：评分基线（每个 turn 加 score）
- v0.5：金蝉脱壳强化（自动 rollback + 世代谱 CLI）
- v0.6：双分支雏形（git worktree 隔离）
- v0.7：自动评分员（pytest + ruff + mypy）
- v0.8：HIL 升级（实时中断）
- v0.9：LangChain 评估（决定脱钩）
- v1.0：稳定双 Agent（A/B 分支 + 角色互换 + 记忆连续 + 自动冻结）
