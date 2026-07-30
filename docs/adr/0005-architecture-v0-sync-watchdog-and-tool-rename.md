# ADR-0005: architecture-v0.md 同步刷（watchdog/ 模块补入 + tools/ 文件名纠正 + 风险档位纠错）

> 状态：已采纳（v0.2.5）
> 时间：2026-07-30（autonomous round 触发，HITL 审批 + supervisor 守护）
> 触发任务：`TASK_TEMPLATES[6]` — "读 docs/architecture-v0.md 和 src/xragent/ 实际代码，看哪里描述过时或缺失"
> 上游 ADR：ADR-0002（首次架构同步）/ ADR-0003（snapshot 保留）/ ADR-0004（工具清单 14 → 15）

## 一、背景

`docs/architecture-v0.md` 在 v0.2.4（ADR-0004）后继续漂移，本轮盘点出 **5 处** 失实，
按严重度排序：

| # | 漂移点 | 严重度 | 失实内容 |
| --- | --- | --- | --- |
| 1 | `watchdog/` 模块整体缺失 | 高（doc 不可导航） | §一 五大核心无 watchdog；§二 模块清单无 watchdog/{init,runtime_state,supervisor}.py |
| 2 | tools/ 三个文件名错 | 高（导航 404） | `file_tools.py` / `web_tools.py` / `evolution_tools.py` 都不存在；实际是 `fs_tools.py` / `web_search.py` / `evolve_tools.py` |
| 3 | `tools/exec_tools.py` 漏列 + run_cmd 错挂 | 中 | doc 把 run_cmd 放在 `file_tools.py` 行末，实际 run_cmd 在 `exec_tools.py` |
| 4 | `curl_url` / `web_search` 风险档位错 | 中（契约错位） | doc §三 表写 `low`，实际 `registry.py` 是 `medium` |
| 5 | §四 关键不变量缺"自愈"行 | 低（完整性） | watchdog/supervisor.py 24h heartbeat 自愈是 ROADMAP v0.1 已交付项，doc 未提及 |

## 二、漂移成因（推测，避免下次重犯）

1. **watchdog/ 缺失**：v0.1 出生版编写 doc 时 watchdog/ 与 autonomous.py 同时成型，但当时
   还在 internal 阶段没列进 §二 模块清单；autonomous.py 被补了，watchdog/ 被遗忘。
   后 v0.1.2 / v0.2.x 多轮 sync（ADR-0002 / 0003 / 0004）都没专门审 §一 五大核心表，
   形成"看 §二 漏掉、§一 没补"的连锁漂移。

2. **tools/ 文件名错**：doc 初版写了语义名（`file_tools` / `web_tools`），实际重构时
   为遵守"按用途而非按行为命名"（fs 是 filesystem 缩写、search 涵盖 search+curl）
   改成 `fs_tools` / `web_search`，但 doc 没跟。

3. **风险档位错**：v0.1 出生版所有外部 IO 都标 `low`；v0.2.x 引入
   "medium = 外部 IO 可观察 / 可中断"档位后，curl_url / web_search 升级到 medium，
   doc §三 表没同步。

## 三、决策

### D1. 在 §一 五大核心"成长"行补 watchdog

不新设"守护"作为第六核心（避免扩五大核心框架），把 watchdog/ 放进"成长"行，
因为"守护子进程存活"与"推动世代演化"都是"Agent 在场时负责让自己活下去"的事。
具体改动：

```
成长 | evolve/metamorphosis.py + evolve/generations.py + autonomous.py（自驱动循环）
       + watchdog/supervisor.py（24h 自愈）+ watchdog/runtime_state.py（心跳文件）
```

并在补充说明加一条 "Watchdog / Supervisor" 短段，说明它与 autonomous 的区别
（autonomous 主动推进任务、watchdog 被动守护存活），防止后续 round 把两者混淆。

### D2. 在 §二 模块清单补 watchdog/ + 修 tools/ 文件名

- `autonomous.py` 行后插入：
  ```
  ├── watchdog/__init__.py
  ├── watchdog/runtime_state.py  # heartbeat 读写 + is_alive / restart_count / bump_restart
  ├── watchdog/supervisor.py     # 24h 子进程守护：fork + heartbeat 检测 + restart + 世代记录
  ```
- 修正 tools/ 区段：
  - `file_tools.py` → `fs_tools.py`（read_file / list_dir / write_file）
  - 新增 `exec_tools.py` 行（run_cmd）
  - `web_tools.py` → `web_search.py`（web_search + curl_url）
  - `evolution_tools.py` → `evolve_tools.py`（propose_self_replace / terminate）

### D3. §三 表头加风险档位说明 + curl_url / web_search 改 medium

§三 顶部加一行 "风险档位：`low`（只读/写受保护路径）·`medium`（外部 IO 但可观察/可中断）·`high`（不可逆写操作，需 HITL）"。
表里 `web_search` / `curl_url` 风险列从 `low` 改 `medium`。

### D4. §四 关键不变量补"子进程异常可自愈"行

新增第 7 行：

```
| 子进程异常可自愈 | watchdog/supervisor.py 定期读 runtime_state.json heartbeat，超过
                    restart_interval_s 未更新则 fork 新子进程并 bump restart_count；
                    Agent 不可改 runtime_state.json（blacklist 保护），自愈不被 Agent 干扰 |
```

### D5. §五 版本对照补 v0.2.5 一行

记录本次同步对应 v0.2.5（沿用 ADR-0002 起的 minor 版本号递增约定），并把 ADR-0005
链接加到文档顶部 preamble。

### D6. 后续约束

- 每次 `TASK_TEMPLATES[6]`（架构 doc 审计）触发时，**必须**额外扫三处：
  §一 五大核心表、§二 模块清单、§三 注册工具表。本次发现 5 处失实里 4 处集中在这三处。
- 任何新增顶层模块（如未来可能的 `audit/` / `telemetry/`），**必须**在首个 PR 同步
  §一 + §二，单独立 ADR 记录决策。
- 任何 tools/* 文件名变更，**必须**在首个 PR 同步 §二 + §三，**禁止**留 stale 文件名。

## 四、影响

- **代码**：本次零代码改动，纯文档同步。
- **测试**：无新增测试；既有 350+ 用例与本次改动正交。
- **风险消除**：
  - 消除"按 doc navigate 找不到 watchdog/"的导航失效；
  - 消除"按 doc 找 file_tools.py 404"的导航失效；
  - 消除"doc 说 curl_url 低风险但 registry 是 medium"的契约错位（未来若 HITL 扩展到 medium 档位，不会因为 doc