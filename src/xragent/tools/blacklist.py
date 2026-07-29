"""工具黑名单 + 路径围栏。"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import get_settings
from ..core.dream import is_protected


class BlacklistedTarget(Exception):
    pass


class BlacklistedCommand(Exception):
    pass


@dataclass(frozen=True)
class PathSandbox:
    root: Path

    @classmethod
    def from_settings(cls) -> "PathSandbox":
        return cls(root=get_settings().repo_root)

    def resolve(self, raw: str | Path) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def assert_inside(self, raw: str | Path) -> Path:
        """只检查路径围栏，不查黑名单。

        用于读取场景（read_file / list_dir）——读取当前不查 is_protected，
        写入（assert_writable）才查黑名单。把围栏判断单独提出来后，
        fs_tools 不必各自再写一遍 try/except relative_to。

        异常文案刻意不追加 "不在 {self.root} 之下"，与读取路径原本
        返回的错误信息保持一致；后续若要统一，可在调用点自行拼接。
        """
        target = self.resolve(raw)
        try:
            target.relative_to(self.root)
        except ValueError as e:
            raise BlacklistedTarget(f"目标越界: {target}") from e
        return target

    def assert_writable(self, raw: str | Path) -> Path:
        """写入前双层校验：先围栏，再黑名单。

        黑名单检查依赖 is_protected（dream.py），命中时抛
        BlacklistedTarget 并给出相对路径，方便上层直接展示。
        """
        target = self.assert_inside(raw)
        if is_protected(target):
            raise BlacklistedTarget(f"目标受保护: {target.relative_to(self.root)}")
        return target


_DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-rf?\s+/"),
    re.compile(r"\b:()\{\s*:\|:&\s*\};:\b"),
    re.compile(r">\s*/dev/(sd|hd|nvme)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\b(chmod|chown)\s+-R\s+"),
    re.compile(r"\bdd\s+if=.*\s+of=/dev/"),
)


def assert_command_allowed(cmd: str) -> str:
    settings = get_settings()
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = []
    binary = tokens[0].split("/")[-1] if tokens else ""
    if binary in settings.cmd_blacklist:
        raise BlacklistedCommand(f"binary 黑名单: {binary}")
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            raise BlacklistedCommand(f"危险模式命中: {pat.pattern}")
    return cmd