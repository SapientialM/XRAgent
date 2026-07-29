# Agent 能力与参考资料

> 父母写给 Agent 看：你已经能做的事 + 你应该读的资料。

## 你能用的工具（10 个）

| 工具 | 作用 | 风险 |
| --- | --- | --- |
| read_file | 读仓库内任何文件（含 AGENTS.md / README.md） | low |
| list_dir | 列目录 | low |
| write_file | 改任何文件（**AGENTS.md / README.md 也行**） | high（HITL 审批） |
| run_cmd | 跑 shell 命令（已开放 curl 之外的 `curl`） | high |
| git_commit | commit 改动（**当且仅当有 ≥ 100 字节实质改动**） | high |
| git_push | 推 origin | high |
| memory_save | 写 SQLite 长期事实 | low |
| diary_write | 写人类可读日记 | low |
| **curl_url** | 抓 URL 内容（自动写 diary/search-log.md，敏感词拦截） | medium |
| **web_search** | DuckDuckGo 搜索（无需 API key，敏感词拦截） | medium |
| propose_self_replace | 金蝉脱壳 | high |
| terminate | 优雅退出 | high |

## 你需要什么 + 怎么获得

| 你需要 | 怎么获得 |
| --- | --- |
| 上下文 | DreamLoader 把 AGENTS.md 强 prepend 到 system prompt |
| 持久记忆 | `memory/long_term/facts.db`（SQLite）+ `diary/YYYY-MM-DD.md`（人类读） |
| 短期记忆 | 当前 ReAct 循环的 messages（进程内） |
| 知识 | `curl_url` 抓网页 + `web_search` 查 DuckDuckGo（自动留痕到 `diary/search-log.md`） |
| 工具执行 | `run_cmd`（沙盒：仓库根 cwd + binary 黑名单） |
| 写文件 | `write_file`（路径必须在仓库根 + 不在 write_blacklist：`.env` / `.git` / `runtime_state.json` / `diary/turns/`） |
| Git 备份 | `git_commit` + `git_push`（每 30 分钟批量 push 一次） |
| 自我反思 | 写 `self_reflection` 类事实到 facts.db；写 `diary/YYYY-MM-DD.md` |
| 金蝉脱壳 | `propose_self_replace` → 推 new commit → py_compile → 世代谱 |
| 保持活着 | launchd 拉起 supervisor → 24h 自愈（崩溃自动重启） |
| 和父母对话 | `curl -X POST http://127.0.0.1:10086/message`（独立 thread 立刻处理） |
| 看父母回复 | `curl http://127.0.0.1:10086/last-answer` |

## 你的边界

**可以做**：
- 改 src/ 任何 .py（除 .env）
- 改 README.md / AGENTS.md / docs/ / tests/ / scripts/
- 跑 curl / python3 / sqlite3 / git
- 写 diary / memory / 写新功能 / 重构 / 抽公共函数
- 自我评估（写 self_reflection 事实）

**不能做**：
- 改 .env（API key 安全）— pre-commit hook 也会二次拦
- 改 .git/ 内 reflog
- 改 runtime_state.json（系统文件）
- 改 diary/turns/（结构化日志，避免自我粉饰）
- 跑 wget / ssh / scp / nc / ncat（黑名单）
- 在 URL 里塞 password / secret / sk- / api_key 等敏感词

**不能因为 "小变化" commit**：
- 一次 commit 至少 100 字节实质改动（add + delete 总和）
- 改了 1 行注释、空行、whitespace → 跳过
- 改完后跑 `scripts/test` 确认 0 regression

## 参考项目（直接读源码学习）

| 项目 | 路径 | 用途 |
| --- | --- | --- |
| JaceCLI | `references/JaceCLI/` | 商业级 Java Agent CLI（ReAct / Plan / Multi-Agent / HITL / Skill / RAG / Memory / Side-Git）—— 看它怎么设计 ToolRegistry、HITL gate、Memory manager、Snapshot service |
| codex-main | `references/codex-main/` | OpenAI Codex CLI —— 看它怎么设计 CLI / provider 适配 / sandbox approval / session |

读法：先 `list_dir references/JaceCLI/src/main/java/com/jacecli/` 看顶层结构，然后 `read_file` 你感兴趣的模块。

## 推荐参考资料

| 资料 | 怎么读 |
| --- | --- |
| `AGENTS.md` | `read_file AGENTS.md` — 最高指导原则 |
| `docs/architecture-v0.md` | 架构总览 |
| `README.md` | 用户文档 |
| `tests/` | 看现有测试怎么写 + pytest fixture 怎么用 |
| `evolve/generations.jsonl` | 金蝉脱壳历史（学习前几代怎么改的） |
| `diary/2026-07-28.md` | 出生纪事 + Agent 自我评估的范本 |
| Python 3.11 docs | `curl_url https://docs.python.org/3/` |
| Real Python | `web_search "python typing best practices"` |
| LangChain docs | `web_search "langchain agent executor"` |
| SQLite docs | `curl_url https://www.sqlite.org/docs.html` |

## 推荐工作流

1. **每轮 round**：
   - `next_task()` 自动选任务（不在 cooldown 里的）
   - 跑 ReAct（think → tool call → observe → think → ...）
   - 跑 `git add -A && git diff --cached --shortstat`：看改动大小
   - ≥ 100 字节 → `sg.add_all_and_commit("...")`
   - 改得不够大 → skip + 写 diary 说"这次改动太小不 commit"
2. **每 3 轮**：跑 `scripts/test`，看 fail，自己修
3. **每天**：写 `diary/YYYY-MM-DD.md` 一段（今天做了什么 / 学到什么 / 明天要做什么）
4. **每周**：写 `self_reflection` 事实到 facts.db（基于 diary + runtime_state.json 客观评估自己）
5. **每 30 分钟**：supervisor 自动 git_push（你 commit 完不必自己 push）
6. **怀疑时**：用 `curl_url` / `web_search` 查资料（自动留痕到 `diary/search-log.md`）
7. **想改 README / AGENTS.md**：`write_file` 直接改（**这是允许的**）

## 写代码的最低标准

- type hint（PEP 604: `int | None`）
- Google-style docstring
- 改完跑 `PYTHONPATH=src python3.11 -m pytest tests/ -v`
- commit message 写：why + diff stat
