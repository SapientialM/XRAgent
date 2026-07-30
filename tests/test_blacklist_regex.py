"""用户可配置 cmd_blacklist_patterns（regex）—— 扩展 binary 黑名单。

覆盖：
  * 自定义 regex 命中 → ``BlacklistedCommand``
  * 自定义 regex 不命中 → 放行（不连带误伤合法命令）
  * 用户 regex 与 binary 黑名单是 *叠加* 关系（独立层级）
  * ``compile_user_patterns`` 兜底：非法 regex 抛 ``ValueError``
  * 默认空 tuple 不会让所有命令被拦（"默认安全" 不等于 "默认全拦"）
  * ``run_cmd`` 端到端：用户 regex 命中 → ``ok=False, error 含 命令被拦截``

不重复 ``tests/test_blacklist.py`` 里已有的 binary 黑名单 + 内置危险模式 +
run_cmd 边界条件；本文件只锁定 *新增的* 第三层（用户 regex）。
"""
from __future__ import annotations

import pytest

from xragent.config.settings import Settings, reset_settings_cache
from xragent.tools.blacklist import (
    BlacklistedCommand,
    assert_command_allowed,
    compile_user_patterns,
)


@pytest.fixture
def patched_settings(monkeypatch):
    """允许每条测试临时切换 ``cmd_blacklist_patterns``，不污染全局缓存。"""

    def _set(patterns: tuple[str, ...] | list[str]) -> Settings:
        reset_settings_cache()
        monkeypatch.setenv("XRAGENT_CMD_BLACKLIST_PATTERNS", "[]")
        # 直接构造，绕过 .env 覆盖
        from xragent.config import settings as settings_mod
        s = Settings(cmd_blacklist_patterns=tuple(patterns))
        monkeypatch.setattr(settings_mod, "_settings", s, raising=False)
        return s

    yield _set

    reset_settings_cache()


# ---------------------------------------------------------------------------
# assert_command_allowed：用户 regex 层
# ---------------------------------------------------------------------------


def test_user_pattern_blocks_matching_command(patched_settings):
    """自定义 regex 命中 → 拦。"""
    patched_settings((r"\brm\b",))
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("rm /tmp/foo")
    assert "用户黑名单命中" in str(ei.value)
    assert "rm" in str(ei.value)


def test_user_pattern_allows_non_matching_command(patched_settings):
    """自定义 regex 不命中 → 放行。"""
    patched_settings((r"\brm\b", r"^wget\s",))
    # echo 不应被任何 pattern 拦
    assert assert_command_allowed("echo hi") == "echo hi"


def test_user_pattern_layer_is_independent_of_binary_blacklist(patched_settings):
    """用户 regex 与 binary 黑名单是叠加关系：
    - 用户 regex 只拦 ``rm`` → ``wget`` 仍由 binary 黑名单拦
    - 用户 regex 同时拦 ``wget`` → 仍命中（顺序无关）。
    """
    patched_settings((r"\brm\b",))
    # 用户 regex 命中 rm
    with pytest.raises(BlacklistedCommand, match="用户黑名单命中"):
        assert_command_allowed("rm /tmp/foo")
    # wget 没在用户 regex 里，但仍在 binary 黑名单里 → 仍拦（"binary 黑名单"）
    with pytest.raises(BlacklistedCommand, match="binary 黑名单"):
        assert_command_allowed("wget http://x")


def test_multiple_user_patterns_all_evaluated(patched_settings):
    """多个 pattern 都应被检查（不是短路在第一个）。"""
    patched_settings((r"\bdd\b", r"\bmkfs\b"))
    with pytest.raises(BlacklistedCommand, match="mkfs"):
        assert_command_allowed("mkfs.ext4 /dev/sdb1")


def test_empty_user_patterns_layer_is_noop(patched_settings):
    """默认空 tuple → 该层是 no-op，不影响合法命令。"""
    patched_settings(())
    # 多个无害命令都应通过
    for cmd in ("echo hi", "ls -la", "python -m xragent.main --smoke"):
        assert assert_command_allowed(cmd) == cmd


def test_user_pattern_uses_re_search_not_fullmatch(patched_settings):
    """pattern 在 cmd 中间匹配也应命中（re.search 语义，不是 re.fullmatch）。

    例子：``foo.sh`` 的 regex 应当拦住 ``bash /tmp/foo.sh``，否则用户写
    ``\\.sh$`` 之类的"扩展名结尾"pattern 就失效了。
    """
    patched_settings((r"\.sh\b",))
    with pytest.raises(BlacklistedCommand, match=r"\.sh"):
        assert_command_allowed("bash /tmp/foo.sh")


def test_user_pattern_layer_does_not_override_built_in(patched_settings):
    """用户 regex 不能 *取消* 内置危险模式（"sudo" 始终被拦，不管用户写了什么）。

    这是"默认安全"的体现：内置模式是硬护栏，用户扩展只能 *加严* 不能 *放宽*。
    """
    patched_settings((r"^ls\b",))  # 用户只拦 ls（含参数）
    # sudo 仍被内置 _DANGEROUS_PATTERNS 拦
    with pytest.raises(BlacklistedCommand, match="危险模式命中"):
        assert_command_allowed("sudo ls")
    # ls 被用户 regex 拦
    with pytest.raises(BlacklistedCommand, match="用户黑名单命中"):
        assert_command_allowed("ls /tmp")
    # echo 仍放行
    assert assert_command_allowed("echo hi") == "echo hi"


# ---------------------------------------------------------------------------
# compile_user_patterns：参数校验
# ---------------------------------------------------------------------------


def test_compile_user_patterns_returns_compiled_objects():
    """合法 regex 字符串列表 → tuple of compiled re.Pattern。"""
    out = compile_user_patterns((r"\brm\b", r"^wget"))
    assert len(out) == 2
    for p in out:
        # re.Pattern 是 compiled 类型
        assert hasattr(p, "search")


def test_compile_user_patterns_rejects_invalid_regex():
    """非法 regex 抛 ``ValueError``——错误尽早失败，不静默忽略。"""
    with pytest.raises(ValueError, match="非法 cmd_blacklist_patterns"):
        compile_user_patterns((r"\brm\b", r"["))  # '[' 是不闭合的字符类


def test_compile_user_patterns_empty_input_returns_empty_tuple():
    """空输入 → 空 tuple（不是抛异常）。"""
    assert compile_user_patterns(()) == ()
    assert compile_user_patterns([]) == ()


# ---------------------------------------------------------------------------
# 端到端：run_cmd 走完整 assert_command_allowed 管道
# ---------------------------------------------------------------------------


def test_run_cmd_blocks_user_pattern_via_full_pipeline(repo_root):
    """用户 regex 命中 → ``run_cmd`` 返回 ``ok=False`` 且 ``error 含 命令被拦截``。"""
    from xragent.tools import exec_tools
    from xragent.config import settings as settings_mod

    reset_settings_cache()
    saved = settings_mod._settings
    settings_mod._settings = Settings(cmd_blacklist_patterns=(r"\brm\b",))
    try:
        r = exec_tools.run_cmd("rm /tmp/should-never-run")
        assert r["ok"] is False
        assert "命令被拦截" in r["error"]
        assert "用户黑名单命中" in r["error"]
    finally:
        settings_mod._settings = saved
        reset_settings_cache()