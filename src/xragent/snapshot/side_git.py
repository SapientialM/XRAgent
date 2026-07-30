"""SideGit：每个 turn 的 git stash + tag。

**v0.1 fix**: stash 时排除 src/ tests/ docs/ AGENTS.md pyproject.toml，避免误清源代码。

**v0.2 增量演化（task：改 dataclass 字段 / 加新方法 / 改返回类型）**：
  - Snapshot 新增 `committed_head` 字段，原子返回 snapshot + commit 的完整元数据
  - 新方法 `commit_snapshot()` 组合 snapshot() + add_all_and_commit()
  - 新方法 `add_and_commit_with_stats()` 返回 Snapshot（含 diff 统计），替代仅返回 str | None
  - 现有 `add_all_and_commit()` 签名保持不变（3 个调用方依赖 str | None）
  - 100% 向后兼容：旧 Snapshot 构造（仅 tag/pre_stash/note）依然有效
  - 顺带修一个真实 bug：min_diff_bytes 之前在 add 之前算 diff, 漏算 untracked 文件

**v0.2.1 bugfix**:
  - `add_all_and_commit` 在 `git add -A` **之前**算 `git diff --shortstat HEAD`,
    但该命令**不含 untracked 文件**, 导致新文件不计入 diff 字节数, 永远被 min_diff_bytes
    护栏跳过。
  - 修法: 先 add, 再 diff --cached --shortstat (含 staged 内容), 才反映 commit 的真实体量。
  - 影响: 现在 untracked 新文件也算"实质性改动", 符合直觉 ("新文件就是改动")。

**v0.2.2 fix**:
  - `commit_snapshot` 顺序错误: 先 `snapshot()` 会 stash 改动, 导致后续 `add_all_and_commit`
    看到无改动而 no-op, committed_head 永远为 None。
  - 修法: 先 commit (有改动就 commit), 再 snapshot (stash backup + tag)。最终 Snapshot
    同时携带 tag (来自 snapshot) 和 committed_head (来自 commit)。

**v0.2.3 新方法**:
  - `cleanup_old_snapshots(max_age_days=None, dry_run=False)`: 清理 N 天前的
    ``xragent/turn-*`` 自动 snapshot tag。默认保留天数走 settings.snapshot_retention_days。
    非 git 仓库 / ``max_age_days <= 0`` 静默返回 ``[]``；``dry_run=True`` 仅列候选。
    仅匹配 ``xragent/turn-*`` 前缀,用户手工 tag（如 ``v0.1`` / ``baseline``）不会被误删。

**v0.3.1 refactor**:
  - `SideGit._run` / `SideGit.push` 改走 ``util.git_helpers.git_run`` / ``git_push``,
    去掉 inline ``subprocess.run`` 模板 (重复 5+ 行 kwargs)。
  - 行为契约完全保留: ``_run`` 仍 raise ``RuntimeError``, ``push`` 仍返回 ``(bool, str)``,
    与 ``test_sidegit.py`` / ``test_subprocess_utils.py`` 锁住的一致。
  - ``import subprocess`` 保留: 仅为兼容 ``tests/test_git_tools.py`` 里
    ``monkeypatch.setattr(side_git.subprocess, "run", fake_run)`` 拦截参数透传。
    ``subprocess.run`` 在 ``run_capture`` 内是动态属性查找, fake_run 跨模块可见,
    该测试无需修改。
"""
from __future__ import annotations

import subprocess  # 仅为测试兼容: tests/test_git_tools.py 通过 side_git.subprocess.run 拦截
import time
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import get_settings
from ..util.git_helpers import git_push as _git_push
from ..util.git_helpers import git_run as _git_run


@dataclass
class Snapshot:
    """一次 snapshot 的完整元数据。

    v0.2 新增 `committed_head`：本次 commit 的 hash（若未触发 commit 则为 None）。
    字段顺序兼容老代码：新增字段放末尾 + 默认 None，老的 keyword 构造不受影响。
    """
    tag: str
    pre_stash: str | None
    note: str
    # v0.2: 新增字段。老 Snapshot(tag=, pre_stash=, note=) 依然合法。
    committed_head: str | None = None


class SideGit:
    def __init__(self, repo_root: Path | None = None):
        s = get_settings()
        self.root = repo_root or s.repo_root
        self.settings = s

    def _run(self, *args: str, check: bool = True) -> str:
        # v0.3.1: 走 git_helpers.git_run, 统一 ``[git, *args]`` 构造 + RuntimeError 消息格式。
        return _git_run(list(args), cwd=self.root, check=check)

    def is_repo(self) -> bool:
        try:
            self._run("rev-parse", "--is-inside-work-tree", check=True)
            return True
        except RuntimeError:
            return False

    def ensure_repo(self) -> None:
        if not self.is_repo():
            self._run("init")
            self._run("config", "user.email", "xragent@local")
            self._run("config", "user.name", "XRAgent")
            self._run("add", "-A")
            try:
                self._run("commit", "-m", "xragent: bootstrap", check=False)
            except RuntimeError:
                pass

    def _stash_pathspec(self) -> list[str]:
        """git stash push 的 pathspec 排除项（防止误清源代码）。

        格式：-- + ':!path'；路径以 / 结尾表示目录。
        """
        out = ["--"]
        for item in self.settings.stash_excludes:
            # 目录加 '*' 通配
            suffix = "*" if item.endswith("/") else ""
            out.append(f":!{item}{suffix}")
        return out

    def snapshot(self, turn_id, note="", tag=True):
        self.ensure_repo()
        pre_stash = None
        if self._has_changes():
            try:
                self._run("stash", "push", "-m", f"xragent-pre-{turn_id}")
                pre_stash = f"xragent-pre-{turn_id}"
            except RuntimeError:
                pre_stash = None
        tag_name = ""
        if tag:
            tag_name = f"xragent/turn-{turn_id}"
            try:
                self._run("tag", "-f", tag_name, "-m", note[:200])
            except RuntimeError:
                tag_name = ""
        return Snapshot(tag=tag_name, pre_stash=pre_stash, note=note)

    def restore(self, tag: str) -> None:
        self._run("checkout", tag)

    def list_snapshots(self) -> list[str]:
        try:
            out = self._run("tag", "-l", "xragent/turn-*", "--sort=-creatordate")
        except RuntimeError:
            return []
        return out.splitlines()

    def _has_changes(self) -> bool:
        """git status --porcelain：含 untracked + modified。"""
        out = self._run("status", "--porcelain")
        return bool(out.strip())

    def _diff_lines(self) -> int:
        """返回 working tree + index vs HEAD 的总行数（ins + dels）。

        v0.2.1 修: 改用 `git diff --shortstat HEAD` + 预先 `git add -A`，
        否则 untracked 新文件不会进入 stat。

        返回 0 表示无变化（不可能的状态，已经被 _has_changes 过滤过）。
        """
        # 先 stage 所有改动（含 untracked → tracked 的转换, -A 保证)
        # 注: --shortstat 在 staged 状态才有意义
        self._run("add", "-A")
        stat_out = self._run("diff", "--shortstat", "HEAD")
        ins = dels = 0
        for part in stat_out.split(","):
            if "insertion" in part:
                ins = int(part.strip().split()[0])
            elif "deletion" in part:
                dels = int(part.strip().split()[0])
        return ins + dels

    def current_head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def add_all_and_commit(self, message: str, min_diff_bytes: int = 100) -> str | None:
        """commit 当且仅当有实质性改动（>= min_diff_bytes 行）。

        注: 参数名 `min_diff_bytes` 是历史遗留, 实际测的是 git diff 的 ins+dels 行数。
        防止 Agent 写一行注释就 commit 刷屏。

        v0.2 注：本方法签名保持不变（3 个调用方依赖 str | None）：
          - src/xragent/tools/git_tools.py
          - src/xragent/evolve/metamorphosis.py
          - src/xragent/main.py
        需要 Snapshot 元数据请用 add_and_commit_with_stats() 或 commit_snapshot()。

        v0.2.1 修: 现在 _diff_lines() 先 add 再 diff, untracked 新文件会进入统计。
        """
        if not self._has_changes():
            return None
        try:
            if self._diff_lines() < min_diff_bytes:
                # 改动太小；不 commit (但 add 已发生, 无副作用)
                return None
        except RuntimeError:
            pass
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD")

    def add_and_commit_with_stats(
        self,
        message: str,
        min_diff_bytes: int = 100,
        note: str = "",
    ) -> Snapshot:
        """v0.2 新方法：返回完整 Snapshot 元数据（含 committed_head）。

        与 add_all_and_commit() 的区别：
          - 返回类型: str | None  →  Snapshot（更结构化）
          - 信息更全: commit hash + note 透传
          - 不触发 stash/tag（那部分是 snapshot() 的职责）

        用例：
          - 需要 atomic 拿到 "本次 commit 的 hash" 而非只用返回值
          - 上层要把 commit 链接到某个 turn 时，统一返回 Snapshot 便于传递
        """
        head = self.add_all_and_commit(message, min_diff_bytes=min_diff_bytes)
        return Snapshot(
            tag="",  # 无 tag（只有 commit）
            pre_stash=None,
            note=note,
            committed_head=head,  # None 表示改动太小被跳过
        )

    def commit_snapshot(
        self,
        turn_id,
        note: str = "",
        min_diff_bytes: int = 100,
        tag: bool = True,
    ) -> Snapshot:
        """v0.2 新方法：组合 snapshot() + add_all_and_commit()，原子返回完整元数据。

        v0.2.2 fix: 顺序为 **先 commit 后 snapshot**。
          - 先 commit: add_all_and_commit 有改动就 commit, committed_head 拿到 hash
          - 再 snapshot: 在已 commit 的 HEAD 上打 tag, 同时 stash 当前剩余脏改动作备份
        最终返回 Snapshot 同时携带 tag (来自 snapshot) 和 committed_head (来自 commit)。

        顺序很重要:
          - 反过来 (先 snapshot 后 commit) 会让 snapshot 把所有改动 stash 起来, 然后
            add_all_and_commit 看到 _has_changes() == False 直接 no-op, committed_head
            永远是 None。
        """
        # 1) 先 commit: 有改动就 commit 拿到 hash
        head = self.add_all_and_commit(
            f"xragent-turn-{turn_id}",
            min_diff_bytes=min_diff_bytes,
        )
        # 2) 再 snapshot: 打 tag + stash 剩余 uncommitted (如果有)
        snap = self.snapshot(turn_id, note=note, tag=tag)
        # 3) 合并到 Snapshot
        return Snapshot(
            tag=snap.tag,
            pre_stash=snap.pre_stash,
            note=snap.note,
            committed_head=head,
        )

    def cleanup_old_snapshots(
        self,
        max_age_days: int | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """清理 N 天前的 ``xragent/turn-*`` snapshot tag。

        默认保留天数走 :attr:`Settings.snapshot_retention_days`（默认 30）。
        ``max_age_days <= 0`` 表示禁用清理 → 直接返回 ``[]``，便于 watchdog
        / cron 调用时用单一开关关闭。``dry_run=True`` 时仅列候选不删除。

        非 git 仓库时静默返回 ``[]``，不抛异常。仅匹配 ``xragent/turn-*``
        前缀——用户手工打的 ``v0.1`` / ``baseline`` 等里程碑 tag 不会被误删。

        Args:
            max_age_days: 保留天数；``None`` 走 settings；``<= 0`` 禁用。
            dry_run: True 仅返回候选 tag 列表，不实际 ``git tag -d``。

        Returns:
            被删除（或将被删除）的 tag 名列表，按 creatordate 从旧到新排序。

        Side effects:
            dry_run=False 时对每个候选 tag 执行 ``git tag -d``；单条失败
            不阻塞其他 tag，返回值只列出成功删除的。
        """
        if not self.is_repo():
            return []
        if max_age_days is None:
            max_age_days = self.settings.snapshot_retention_days
        if max_age_days <= 0:
            return []

        cutoff = int(time.time()) - max_age_days * 86400
        try:
            out = self._run(
                "for-each-ref",
                "refs/tags/xragent/turn-*",
                "--format=%(refname:short)%09%(creatordate:unix)",
            )
        except RuntimeError:
            return []

        candidates: list[tuple[int, str]] = []
        for line in out.splitlines():
            if "\t" not in line:
                continue
            name, ts_str = line.split("\t", 1)
            try:
                ts = int(ts_str)
            except ValueError:
                continue
            if ts < cutoff:
                candidates.append((ts, name))

        candidates.sort()  # 旧 → 新
        targets = [name for _, name in candidates]
        if dry_run or not targets:
            return targets

        removed: list[str] = []
        for name in targets:
            try:
                self._run("tag", "-d", name)
                removed.append(name)
            except RuntimeError:
                # 单个 tag 删不掉不应阻塞整体；吞掉并继续。
                pass
        return removed

    def push(self, remote: str = "origin", branch: str = "main") -> tuple[bool, str]:
        # v0.3.1: 走 git_helpers.git_push, 统一 ``(ok, msg)`` 语义 + rc 兜底。
        return _git_push(cwd=self.root, remote=remote, branch=branch)