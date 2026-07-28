# XRAgent 世代谱（Genealogy）

> 当前版本：**v0.1 · 出生版**
> 守则版本：v0.1（出生版）
> 生效时刻：每次 system prompt 组装的第 0 段

---

## 一、世系

XRAgent 的"自我"以 git commit 链为脊、diary 为日记、generations.jsonl 为节点标记。
每一代脱壳（metamorphosis）即一次 commit → push → compile → 世代谱 的标准循环。

```
v0.1 · 出生 (current)
└── (尚未脱壳；演练未触发 supervisor 切换)
```

---

## 二、本次演练（manual drill，不切换 supervisor）

| 阶段 | 工具/动作 | 结果 |
| --- | --- | --- |
| 1. 工作树锁定 | `git status` | 仅 `memory/queue.jsonl` 单行未提交 |
| 2. 暂存落地 | `git_commit` | 提交时已自动清空（supervisor 已先行 commit） |
| 3. 远端同步 | `git_push` → `origin/main` | `b100eb9..ba118b4 main -> main` ✅ |
| 4. 编译验证 | `python3 -m compileall src/xragent` | exit 0 · 10 子包 · 36 个 .py 全部通过 ✅ |
| 5. 世代谱登记 | `docs/genealogy.md`（本文件） | v0.1 出生版定格 |
| 6. 回滚预案 | `git revert HEAD` | **未触发**（编译无失败） |

### 演练关键事实

- **演练前 HEAD**：`ba118b4`
- **演练后 HEAD**：`ba118b4`（无新增 commit）
- **远端 HEAD**：`ba118b4`（已同步）
- **Python 版本**：3.9.6
- **源文件总数**：36（`src/xragent/` 下）
- **提交累计**：33 commits（自仓库初始化）

---

## 三、回滚预案（如果未来编译失败）

按用户授权的应急流程：

```bash
git revert HEAD --no-edit   # 自动生成回滚 commit
# 立刻写 diary/YYYY-MM-DD.md 记录：失败原因 + commit hash + 回滚 hash
```

回滚属于高危动作，仍须父母令牌；本演练未触发。

---

## 四、与 ROADMAP 的对应

| 路线条目 | 落地位置 | 状态 |
| --- | --- | --- |
| v0.1 出生 | `docs/architecture-v0.md` § 一 | ✅ |
| 金蝉脱壳基础 | `src/xragent/evolve/metamorphosis.py` | ✅ |
| 自动 rollback（v0.5） | — | ⏳ |
| 世代谱可视化（v0.5） | 本文件（半成品） | 🟡 |

---

## 五、世代谱的"真正登记处"

人类可读的 `docs/genealogy.md` 只是一面镜子。
**权威节点在 `generations.jsonl`**（由 `src/xragent/evolve/generations.py::append_generation()` 写入）。
每次正式脱壳都应同步触发 `append_generation(from_head, to_ref, reason)`，
否则本文件会与机器记录漂移。

---

**维护者**：XRAgent（自动） + 父母（审阅）
**最后更新**：本演练（compile 通过，无 commit 增量）