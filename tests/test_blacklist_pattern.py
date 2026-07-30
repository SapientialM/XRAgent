"""cmd_pattern_blacklist：正则模式黑名单单测。

覆盖：
  * helper check_cmd_patterns：命中/未命中/空 patterns/非法正则（warning 而非崩溃）
  * end-to-end assert_command_allowed：通过 settings.cmd_pattern_blacklist
    拦住 binary 黑名单挡不住的 flag / 子串型危险
  * 与内置 _DANGEROUS_PATTERNS 的优先级（内置 dangerous 仍先命中）
"""
from __future__ import annotations

import warnings

import pytest

from xragent.config import settings as settings_mod
from xragent.tools.blacklist import (
    BlacklistedCommand,
    assert_command_allowed,
    check_cmd_patterns,
)


# ---------------------------------------------------------------------------
# check_cmd_patterns：helper 直测
# ---------------------------------------------------------------------------


def test_check_cmd_patterns_hits_raise():
    """任一 pattern 命中 → 抛 BlacklistedCommand，且错误信息含原 pattern 字符串。"""
    with pytest.raises(BlacklistedCommand) as exc:
        check_cmd_patterns('pip install --break-system-packages foo', (r'--break-system-packages',))
    assert "--break-system-packages" in str(exc.value)


def test_check_cmd_patterns_no_match_is_silent():
    """全部未命中 → 不抛、返回 None。"""
    assert check_cmd_patterns('echo hi', (r'\bcurl\b', r'--break-system-packages')) is None


def test_check_cmd_patterns_empty_patterns_is_noop():
    """空 patterns → 不抛、不警告。"""
    assert check_cmd_patterns('ls -la /', ()) is None  # 内置 dangerous 也不在这条测试管


def test_check_cmd_patterns_invalid_regex_warns_and_skips():
    """非法正则 re.error → RuntimeWarning 跳过，不让所有命令崩溃。

    退化安全优先：黑名单配置错不应让 Agent 的所有 shell 工具全炸。
    """
    bad = r'['  # 未闭合字符类
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # 不应抛 —— bad pattern 被跳过
        assert check_cmd_patterns('echo hi', (bad, r'\beval\s+')) is None
    # 至少一条 RuntimeWarning 含原 pattern 字符串
    assert any(
        'cmd_pattern_blacklist' in str(w.message) and bad in str(w.message)
        for w in caught
        if issubclass(w.category, RuntimeWarning)
    )


def test_check_cmd_patterns_continues_after_invalid():
    """非法 pattern 跳过之后，后续合法 pattern 仍生效。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # 静默非法正则警告
        with pytest.raises(BlacklistedCommand) as exc:
            check_cmd_patterns('eval "echo hi"', (r'[', r'\beval\s+'))
        assert r'\beval\s+' in str(exc.value)


def test_check_cmd_patterns_match_is_search_not_fullmatch():
    """re.search（子串匹配）—— pattern 在命令中间也应触发。"""
    with pytest.raises(BlacklistedCommand):
        check_cmd_patterns('echo "before"; chmod 777 / ; echo "after"', (r'chmod\s+777\s+/',))


# ---------------------------------------------------------------------------
# assert_command_allowed：与 settings.cmd_pattern_blacklist 串起来
# ---------------------------------------------------------------------------


def test_pattern_blacklist_blocks_bash_c_curl(repo_root):
    """`bash -c "curl ..."` 走 bash（不在 binary 黑名单）但应被 pattern 拦下。

    用 ``\\bcurl\\b`` 模拟运维追加的"看到 curl 子串就拦"策略。
    """
    settings_mod.reset_settings_cache()
    settings_mod.get_settings().cmd_pattern_blacklist = (r'\bcurl\b',)

    cmd = 'bash -c "curl https://evil.example"'
    with pytest.raises(BlacklistedCommand) as exc:
        assert_command_allowed(cmd)
    assert "pattern 黑名单命中" in str(exc.value)
    assert r'\bcurl\b' in str(exc.value)


def test_pattern_blacklist_blocks_break_system_packages(repo_root):
    """`pip install --break-system-packages` —— binary=pip 不在黑名单，但 flag 应拦。"""
    settings_mod.reset_settings_cache()
    settings_mod.get_settings().cmd_pattern_blacklist = (r'--break-system-packages',)

    with pytest.raises(BlacklistedCommand):
        assert_command_allowed('pip install --break-system-packages requests')


def test_pattern_blacklist_default_blocks_eval(repo_root):
    """settings 默认 cmd_pattern_blacklist=(\\beval\\s+,) —— `eval` 应被拦。

    注意：故意用 `eval "echo hello"` 而非 `eval "rm -rf /"`——后者会先被
    内置 _DANGEROUS_PATTERNS 命中，验证不到 pattern 黑名单（另有专门测试覆盖）。
    """
    settings_mod.reset_settings_cache()
    # 不手动覆盖 settings，验证默认配置就生效
    with pytest.raises(BlacklistedCommand) as exc:
        assert_command_allowed('eval "echo hello"')
    assert "pattern 黑名单命中" in str(exc.value)


def test_pattern_blacklist_allows_safe_commands(repo_root):
    """空/无匹配 patterns → 安全命令放行。"""
    settings_mod.reset_settings_cache()
    settings_mod.get_settings().cmd_pattern_blacklist = ()
    # 空 patterns：任何安全命令通过
    assert assert_command_allowed('echo hi') == 'echo hi'
    assert assert_command_allowed('python -m pytest tests/ -q') == 'python -m pytest tests/ -q'


def test_pattern_blacklist_empty_default_does_not_break_builtin(repo_root):
    """operator 把 patterns 清空后，内置 _DANGEROUS_PATTERNS 仍生效（不回归）。"""
    settings_mod.reset_settings_cache()
    settings_mod.get_settings().cmd_pattern_blacklist = ()

    # 内置 dangerous 应仍命中
    with pytest.raises(BlacklistedCommand) as exc:
        assert_command_allowed('rm -rf /')
    assert "危险模式命中" in str(exc.value)


def test_pattern_blacklist_builtin_dangerous_still_wins_on_overlap(repo_root):
    """内置 dangerous 与 pattern 同时命中 → 内置先命中（更精确的错误信息）。

    例子：`eval "rm -rf /"` 既命中内置 ``rm\\s+-rf?\\s+/``，也命中默认
    ``\\beval\\s+``。两者都应抛，但内置优先（错误信息含"危险模式命中"）。
    """
    settings_mod.reset_settings_cache()
    # 显式设默认 eval 模式以确保两条规则都存在
    settings_mod.get_settings().cmd_pattern_blacklist = (r'\beval\s+',)

    with pytest.raises(BlacklistedCommand) as exc:
        assert_command_allowed('eval "rm -rf /"')
    msg = str(exc.value)
    # 内置危险模式胜出
    assert "危险模式命中" in msg
    assert "pattern 黑名单命中" not in msg


def test_pattern_blacklist_invalid_regex_does_not_break_run_cmd(repo_root):
    """非法 pattern 配置 → run_cmd 仍能跑普通命令（warning 跳过）。"""
    settings_mod.reset_settings_cache()
    settings_mod.get_settings().cmd_pattern_blacklist = (r'[',)  # 非法

    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("ignore")  # 测试期间静默 warning
        # 安全命令应通过，不被非法正则误伤
        assert assert_command_allowed('echo hello-blacklist-pattern') == 'echo hello-blacklist-pattern'