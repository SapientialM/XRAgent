# ADR-0008: 抽取 util/heartbeat.py（util/ 5→6 模块）

- 状态：已应用
- 触发 commit：1a3d1d42（v0.2.7 / round 158）
- 关联文件：`src/xragent/util/heartbeat.py`（新增 76 行）、
  `src/xragent/main.py`（-26 / +10，net -16 行）

## 上下文

`main.py` 里 `cmd_interactive` 的 `heartbeat_worker` 和 `cmd_autonomous` 的
`_heartbeat_loop` 是同一段 7 行模板：

```
while not <stop>:
    try:
        rs.heartbeat()
    except Exception:
        pass
    wait(<interval>)
```

差别只有两点：停止条件（`threading.Event.is_set` vs `dict["v"]`）+ 间隔来源
（`settings.heartbeat_interval_s` vs 写死 5s）。复制粘贴，连"吞异常"
（`except Exception: pass`）的细节都一致。

`util/__init__.py` 顶部明确说"按出现 2+ 次且 ≥5 行原则抽出，避免过早抽象"。
这次正好踩到阈值（2 处 × 7 行 = 14 行）。

## 决策

抽 `src/xragent/util/heartbeat.py::start_heartbeat_thread(stop_predicate,
interval_s, name) -> threading.Thread`，签名接受 callable 形式的停止谓词
（兼容 Event.is_set 和 dict 旗标两种风格）。`main.py` 两处都改为一行调用。

不返回 `Thread` 句柄——调用方只关心"后台跑 + 退出时能停"，daemon=True 让进程
退出时直接终止；若以后需要 join() 再加返回 `Thread` 的 API。

## 边界

- 异常一律吞（`except Exception: pass`）——心跳失败不应让守护线程崩。
  若上层需要心跳失败告警，由 `runtime_state.heartbeat` 自己在写入端处理。
- `stop_predicate` 在每次循环开头、每次 wait 之前各调一次，保证响应延迟 ≤
  `interval_s`，且退出时不会卡在 wait 上。

## 影响

- util/ 模块数从 5 → 6：`json_utils / jsonl_utils / subprocess_utils /
  diary_archive / git_helpers / heartbeat`。
- `architecture-v0.md` §一 / §二 / §五同步到 6 个模块，并加版本对照行。
- main.py -26 / +10，net -16 行；行为不变（已用 `Event`-based 和 `dict`-based
  两种停止条件各自烟雾测试，线程在停止信号后 50ms 内 join 干净）。