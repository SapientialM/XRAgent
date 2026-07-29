"""SideGit：每个 turn 的 git stash + tag。

**v0.1 fix**: stash 时排除 src/ tests/ docs/ AGENTS.md pyproject.toml，避免误清源代码。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import get_settings


@dataclass
class Snapshot:
    tag: str
    pre_stash: str | None
    note: str


class SideGit:
    def __init__(self, repo_root: Path | None = None):
        s = get_settings()
        self.root = repo_root or s.repo_root
        self.settings = s

    def _run(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
        return result.stdout.strip()

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
        out = self._run("status", "--porcelain")
        return bool(out.strip())

    def current_head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def add_all_and_commit(self, message: str, min_diff_bytes: int = 100) -> str | None:
        """commit 当且仅当有实质性改动（>= min_diff_bytes 字节）。

        防止 Agent 写一行注释就 commit 刷屏。
        """
        if not self._has_changes():
            return None
        # 统计本次 diff 的字节/行数；太小就跳过
        try:
            stat_out = self._run("diff", "--shortstat", "HEAD")
            # 形如 "1 file changed, 2 insertions(+), 1 deletion(-)"
            ins = dels = 0
            for part in stat_out.split(","):
                if "insertion" in part:
                    ins = int(part.strip().split()[0])
                elif "deletion" in part:
                    dels = int(part.strip().split()[0])
            if (ins + dels) < min_diff_bytes:
                # 改动太小；不 commit
                return None
        except RuntimeError:
            pass
        self._run("add", "-A")
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD")

    def push(self, remote: str = "origin", branch: str = "main") -> tuple[bool, str]:
        result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        return (result.returncode == 0, (result.stderr or result.stdout).strip())
