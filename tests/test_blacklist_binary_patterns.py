"""cmd_blacklist 扩展形态 (glob / re) 测试。

锁定契约:
  * 向后兼容 — 默认配置 (精确名列表) 文案 byte-equal 旧版
  * glob: 前缀 — fnmatch 匹配 binary basename,大小写敏感
  * re: 前缀 — regex re.search 匹配 binary basename
  * 非法 regex — 编译期 ValueError,与 compile_user_patterns 兜底一致
  * 混合列表 — exact + glob + re 同 tuple 共存
  * shlex 失败的命令 — 不命中 binary 层,落到危险模式/用户 regex 层
"""
from __future__ import annotations

import pytest

from xragent.config.settings import get_settings
from xragent.tools.blacklist import (
    BlacklistedCommand,
    _compile_binary_blacklist,
    assert_command_allowed,
)


@pytest.fixture
def fresh_cmd_blacklist():
    """每次测试改 cmd_blacklist 后自动还原;基于 conftest 已构造的 settings instance。"""
    s = get_settings()
    yield s


# ---------------------------------------------------------------------------
# 向后兼容 — 默认精确名与旧版文案 byte-equal
# ---------------------------------------------------------------------------


def test_exact_match_blocks_default_binaries():
    """默认 5 条精确名 (wget/ssh/scp/nc/ncat) 全部按旧文案拦。"""
    # 注: curl 不在默认 cmd_blacklist (settings 注释: "curl 已开放给 web_search 工具")
    for cmd in (
        "wget http://x",
        "ssh user@host",
        "scp a b",
        "nc -l 1234",
        "ncat -l 1",
    ):
        with pytest.raises(BlacklistedCommand) as ei:
            assert_command_allowed(cmd)
        # 文案 byte-equal 旧版,让外部 grep / 日志断言不漂移
        assert str(ei.value).startswith("binary 黑名单: "), str(ei.value)
        assert "←" not in str(ei.value)  # 精确名不带规则后缀


def test_exact_match_is_case_sensitive():
    """精确名严格区分大小写 — 大写 wget 应放行 binary 层。"""
    assert assert_command_allowed("WGET http://x") == "WGET http://x"


def test_exact_match_uses_basename_not_full_path():
    """/usr/bin/wget 等路径前缀不影响精确名匹配。"""
    with pytest.raises(BlacklistedCommand):
        assert_command_allowed("/usr/bin/wget http://x")


# ---------------------------------------------------------------------------
# glob: 前缀 — fnmatch 匹配
# ---------------------------------------------------------------------------


def test_glob_pattern_blocks_family(fresh_cmd_blacklist):
    """glob:ssh* 拦截 ssh / sshd / ssh-agent ( * 匹配任意字符序列 )。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("glob:ssh*",)
    for cmd in ("ssh user@host", "sshd -D", "ssh-agent -k", "ssh2 -V"):
        with pytest.raises(BlacklistedCommand) as ei:
            assert_command_allowed(cmd)
        assert "glob" in str(ei.value)
        assert "glob:ssh*" in str(ei.value)


def test_glob_pattern_does_not_match_unrelated_prefix(fresh_cmd_blacklist):
    """glob:ssh* 不拦 mysql / python 等完全无关的 binary。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("glob:ssh*",)
    assert assert_command_allowed("python -V") == "python -V"
    assert assert_command_allowed("mysql -uroot") == "mysql -uroot"


def test_glob_pattern_is_case_sensitive(fresh_cmd_blacklist):
    """glob 大小写敏感: SSH 不在 ssh* 范围。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("glob:ssh*",)
    assert assert_command_allowed("SSH user@host") == "SSH user@host"


def test_glob_question_mark_matches_single_char(fresh_cmd_blacklist):
    """glob:nc? 拦 ncA 单字符不拦 ncAB 多字符 ( ? 匹配单字符,与 * 区分 )。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("glob:nc?",)
    # ncc: 3 字符,匹配 nc?
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("ncc -l 1")
    assert "glob" in str(ei.value)
    # ncat: 4 字符,不匹配 nc?
    assert assert_command_allowed("ncat -l 1") == "ncat -l 1"


# ---------------------------------------------------------------------------
# re: 前缀 — regex re.search 匹配
# ---------------------------------------------------------------------------


def test_re_pattern_anchored_blocks_exact_match(fresh_cmd_blacklist):
    """re:^wget$ 只拦 wget,不拦 wget2 / wget-old。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("re:^wget$",)
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("wget http://x")
    assert "re" in str(ei.value)
    assert "re:^wget$" in str(ei.value)


def test_re_pattern_unanchored_blocks_family(fresh_cmd_blacklist):
    """re:^wget 拦 wget / wget-old。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("re:^wget",)
    with pytest.raises(BlacklistedCommand):
        assert_command_allowed("wget http://x")
    with pytest.raises(BlacklistedCommand):
        assert_command_allowed("wget-old --help")


def test_re_pattern_character_class(fresh_cmd_blacklist):
    """re:ssh[0-9]? 拦截 ssh / ssh0 / ssh1。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("re:ssh[0-9]?",)
    for cmd in ("ssh user@host", "ssh0 --help", "ssh1 -V"):
        with pytest.raises(BlacklistedCommand) as ei:
            assert_command_allowed(cmd)
        assert "re" in str(ei.value)


def test_re_pattern_invalid_regex_raises_value_error():
    """非法 regex (re:[ 编译失败) → ValueError。"""
    with pytest.raises(ValueError) as ei:
        _compile_binary_blacklist(("re:[",))
    assert "非法 cmd_blacklist re-pattern" in str(ei.value)


def test_re_pattern_invalid_in_settings_blocks_cmd_via_config_error(fresh_cmd_blacklist):
    """非法 re: 配置进入 settings → assert_command_allowed 仍要拦截 (兜底)。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("re:[",)
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("echo hi")
    assert "binary 黑名单配置非法" in str(ei.value)


# ---------------------------------------------------------------------------
# 混合列表 — exact + glob + re 同 tuple 共存
# ---------------------------------------------------------------------------


def test_mixed_blacklist_matches_each_kind(fresh_cmd_blacklist):
    """(exact, glob, re) 混合 — 每种形态都按各自语义工作,文案带规则来源。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("wget", "glob:ssh*", "re:^ncx$")

    # exact: wget — 文案 byte-equal 旧版
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("wget http://x")
    assert str(ei.value).startswith("binary 黑名单: ")
    assert "←" not in str(ei.value)

    # glob: ssh*
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("sshd -D")
    assert "(glob)" in str(ei.value)
    assert "glob:ssh*" in str(ei.value)

    # re: ^ncx$
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("ncx --help")
    assert "(re)" in str(ei.value)
    assert "re:^ncx$" in str(ei.value)


def test_mixed_blacklist_unmatched_passes_through(fresh_cmd_blacklist):
    """混合列表中,未被任何规则拦的命令放行 binary 层。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("wget", "glob:ssh*", "re:^ncx$")
    assert assert_command_allowed("python -V") == "python -V"


# ---------------------------------------------------------------------------
# shlex 失败兜底
# ---------------------------------------------------------------------------


def test_shlex_failure_does_not_match_binary_layer(fresh_cmd_blacklist):
    """shlex.split 失败 (未闭合引号) → tokens=[] → binary="" → binary 层全部不命中。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("wget", "glob:ssh*", "re:^ncx$")
    cmd = 'echo "unclosed'
    try:
        assert_command_allowed(cmd)
    except BlacklistedCommand as e:
        assert "binary 黑名单" not in str(e), (
            f"shlex 失败时不应触发 binary 层: {e}"
        )


# ---------------------------------------------------------------------------
# _compile_binary_blacklist 纯函数契约
# ---------------------------------------------------------------------------


def test_compile_empty_tuple_returns_empty_rules():
    """空 tuple → 空规则集 (settings 默认 fallback 用)。"""
    assert _compile_binary_blacklist(()) == ()


def test_compile_preserves_source_for_error_messages():
    """规则 source 字段保留原文 — 错误文案 grep 用。"""
    rules = _compile_binary_blacklist(("wget", "glob:ssh*", "re:^curl$"))
    sources = [r.source for r in rules]
    assert sources == ["wget", "glob:ssh*", "re:^curl$"]


def test_compile_rule_kinds():
    """规则 kind 字段正确分类 — 方便日志/统计。"""
    rules = _compile_binary_blacklist(("wget", "glob:ssh*", "re:^curl$"))
    kinds = [r.kind for r in rules]
    assert kinds == ["exact", "glob", "re"]


def test_compile_glob_empty_pattern_matches_only_empty():
    """glob: 后空 → "" pattern,fnmatchcase("", "") == True,binary 空字符串命中。

    注意:这不是 bug,是配置错误行为。测试锁定行为以便审计。
    """
    rules = _compile_binary_blacklist(("glob:",))
    assert len(rules) == 1
    assert rules[0].matcher("") is True
    assert rules[0].matcher("anything") is False  # 非空 binary 不命中


# ---------------------------------------------------------------------------
# 与 Settings.cmd_blacklist_patterns 互不干扰
# ---------------------------------------------------------------------------


def test_re_prefix_does_not_leak_into_cmd_blacklist_patterns(fresh_cmd_blacklist):
    """binary 黑名单的 re: 规则只匹配 binary basename,不影响整条 cmd 的 user-pattern 层。"""
    s = fresh_cmd_blacklist
    s.cmd_blacklist = ("re:^wget$",)  # 只拦 wget
    s.cmd_blacklist_patterns = (r"rm\s+-rf\s+/",)
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("rm -rf /")
    # 走的是 user-pattern 层,不是 binary 层
    assert "binary 黑名单" not in str(ei.value), str(ei.value)