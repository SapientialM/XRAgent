"""工具黑名单 + 路径围栏。"""
from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

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
    def from_settings(cls) -> PathSandbox:
        """从全局 ``get_settings()`` 构造一个 ``PathSandbox`` 实例。

        ``root`` 取自 ``settings.repo_root``（仓库根），所有后续 ``resolve`` /
        ``assert_inside`` / ``assert_writable`` 都以此为围栏基准。

        Returns:
            PathSandbox: ``root == settings.repo_root`` 的新实例（frozen）。
        """
        return cls(root=get_settings().repo_root)

    def resolve(self, raw: str | Path) -> Path:
        """把 ``raw`` 解析成以 ``self.root`` 为基准的绝对路径。

        行为细节：
          * 相对路径 → 先 ``self.root / raw`` 再 ``.resolve()``；
          * 绝对路径 → 直接 ``.resolve()``（不会绕回 ``self.root``）；
          * ``..`` 与符号链接会被 ``Path.resolve()`` 规范化；
          * 返回值 ``Path`` 不保证磁盘上已存在（仅做字符串 / symlink 解析）。

        Args:
            raw: 原始路径；接受 ``str`` 或任何 ``os.PathLike``（如 ``Path``）。

        Returns:
            Path: 规范化后的绝对路径（``is_absolute()`` 为 True）。
        """
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
    re.compile(r"\b:(){\s*:\|:&\s*};:\b"),
    re.compile(r">\s*/dev/(sd|hd|nvme)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\b(chmod|chown)\s+-R\s+"),
    re.compile(r"\bdd\s+if=.*\s+of=/dev/"),
)


# === cmd_blacklist 条目形态 ===
#
# 每个条目按 *前缀* 解析成一条匹配规则:
#   * 无前缀 → exact:   binary basename 完全相等 (向后兼容)
#   * "glob:" → glob:   fnmatchcase 匹配 binary basename
#   * "re:"   → re:     re.search 匹配 binary basename
#
# 整条 cmd 的 regex 匹配已由 cmd_blacklist_patterns 覆盖,不在本层重复。
# 非法 regex 在编译期抛 ValueError,与 compile_user_patterns 兜底一致。
BinaryRuleKind = Literal["exact", "glob", "re"]


@dataclass(frozen=True)
class _BinaryRule:
    """cmd_blacklist 一条规则: source 是原文, matcher 接收 binary basename 返回 bool。"""
    source: str
    kind: BinaryRuleKind
    matcher: Callable[[str], bool]


def _compile_binary_blacklist(items: tuple[str, ...] | list[str]) -> tuple[_BinaryRule, ...]:
    """把 cmd_blacklist 编译成规则列表。

    前缀约定:
      * ``"re:..."`` → regex (binary basename 上做 ``re.search``)
      * ``"glob:..."`` → fnmatch 风格 (binary basename, case-sensitive)
      * 无前缀 → 精确名 (``binary == item``),向后兼容旧配置

    非法 regex 直接抛 ``ValueError``——默认安全:错误的拦截规则宁可让
    启动失败 (运维一眼能看到),也别静默忽略变成漏洞。glob 不做语法校验
    (fnmatch 不会失败),按字面匹配。
    """
    rules: list[_BinaryRule] = []
    for item in items:
        if item.startswith("re:"):
            pat = item[3:]
            try:
                regex = re.compile(pat)
            except re.error as e:
                raise ValueError(f"非法 cmd_blacklist re-pattern {item!r}: {e}") from e
            rules.append(_BinaryRule(
                source=item,
                kind="re",
                matcher=lambda b, r=regex: r.search(b) is not None,
            ))
        elif item.startswith("glob:"):
            pat = item[5:]
            rules.append(_BinaryRule(
                source=item,
                kind="glob",
                matcher=lambda b, p=pat: fnmatch.fnmatchcase(b, p),
            ))
        else:
            rules.append(_BinaryRule(
                source=item,
                kind="exact",
                matcher=lambda b, i=item: b == i,
            ))
    return tuple(rules)


def compile_user_patterns(patterns: tuple[str, ...] | list[str]) -> tuple[re.Pattern[str], ...]:
    """把用户传入的 regex 字符串列表编译成 compiled pattern 列表。

    非法 regex 直接抛 ``ValueError``——"默认安全"：错误的拦截规则宁可让
    启动失败（运维一眼能看到），也别静默忽略变成漏洞。调用方负责捕获
    后向上抛 ``BlacklistedCommand`` 或 ``SettingsError``。
    """
    compiled: list[re.Pattern[str]] = []
    for raw in patterns:
        try:
            compiled.append(re.compile(raw))
        except re.error as e:
            raise ValueError(f"非法 cmd_blacklist_patterns 条目 {raw!r}: {e}") from e
    return tuple(compiled)


def assert_command_allowed(cmd: str) -> str:
    """三层叠加拦截：binary 黑名单 → 内置危险模式 → 用户自定义 regex。

    顺序说明:
      1. **binary 黑名单**: ``Settings.cmd_blacklist`` — 三种形态 (exact /
         glob / re) 匹配 binary basename;精确名模式与旧版文案 byte-equal。
      2. ``_DANGEROUS_PATTERNS``: 硬编码、不可关闭的安全护栏。
      3. ``Settings.cmd_blacklist_patterns``: 用户/运维扩展入口,tuple of
         regex 字符串;对整条 cmd 走 ``re.search``。

    任意一层命中即抛 ``BlacklistedCommand``,错误文案携带具体命中原因
    (binary 名 / 危险模式 / 用户 pattern 字面 / 规则前缀),方便 HITL
    审批人判断。
    """
    settings = get_settings()
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = []
    binary = tokens[0].split("/")[-1] if tokens else ""

    # 第 1 层: binary 黑名单 (exact / glob / re 三种形态)
    try:
        binary_rules = _compile_binary_blacklist(settings.cmd_blacklist)
    except ValueError as e:
        # 配置错误不应阻塞合法命令: 把 binary 黑名单退化为"空规则集",
        # 但保留 stderr 等价物 (错误信息塞进 BlacklistedCommand 文案),
        # 让运维在审批日志里能一眼看到。
        raise BlacklistedCommand(f"binary 黑名单配置非法: {e}") from e
    for rule in binary_rules:
        if rule.matcher(binary):
            if rule.kind == "exact":
                # 向后兼容: 旧文案 "binary 黑名单: <name>" byte-equal
                raise BlacklistedCommand(f"binary 黑名单: {binary}")
            raise BlacklistedCommand(f"binary 黑名单 ({rule.kind}): {binary} ← {rule.source}")

    # 第 2 层: 内置危险模式
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            raise BlacklistedCommand(f"危险模式命中: {pat.pattern}")

    # 第 3 层: 用户自定义 regex (整条 cmd)
    try:
        user_patterns = compile_user_patterns(settings.cmd_blacklist_patterns)
    except ValueError as e:
        raise BlacklistedCommand(f"用户黑名单配置非法: {e}") from e
    for pat in user_patterns:
        if pat.search(cmd):
            raise BlacklistedCommand(f"用户黑名单命中: {pat.pattern}")
    return cmd