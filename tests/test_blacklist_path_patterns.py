"""cmd_blacklist 路径级形态 (path: / path-glob:) 测试。

锁定契约:
  * path: 前缀 — regex (re.search) 作用对象是 **整条路径** (含目录),
    用于把某个可执行文件的特定安装位置精确封掉
  * path-glob: 前缀 — fnmatch 作用对象是整条路径
  * path* 与 basename 类规则 (exact / glob / re) 在同一条命令上是
    独立判定: 旧规则只匹配 basename, 不会因为名字一样就误伤不同
    安装位置的 binary
  * path* 规则误用 regex 编译失败 — ValueError (与 re: 路径一致,
    "默认安全": 配置错误宁可启动失败也别静默)
  * 错误文案携带 整条路径 + 规则前缀 + 原文, 方便 HITL 审批人定位
  * 空命令 / shlex 失败 — path* 不会触发 (target == "")
  * run_cmd 端到端: path* 命中 → ok=False, error 含 "binary 黑名单"

不重复 ``tests/test_blacklist_binary_patterns.py`` 已覆盖的 exact /
glob / re basename 路径, 本文件只锁定 *新增的* path* (整条路径) 维度。
"""
from __future__ import annotations

import pytest

from xragent.config import settings as settings_mod
from xragent.config.settings import Settings, reset_settings_cache
from xragent.tools.blacklist import (
    BlacklistedCommand,
    _compile_binary_blacklist,
    assert_command_allowed,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_settings(monkeypatch):
    """临时切换 cmd_blacklist, 不污染全局 settings 缓存。"""

    def _set(items: tuple[str, ...] | list[str]) -> Settings:
        reset_settings_cache()
        monkeypatch.setenv("XRAGENT_CMD_BLACKLIST", "[]")
        s = Settings(cmd_blacklist=tuple(items))
        monkeypatch.setattr(settings_mod, "_settings", s, raising=False)
        return s

    yield _set

    reset_settings_cache()


# ---------------------------------------------------------------------------
# _compile_binary_blacklist 编译层
# ---------------------------------------------------------------------------


def test_compile_path_with_simple_substring_matches_full_path():
    """path:<substring> — re.search 子串匹配整条路径。"""
    rules = _compile_binary_blacklist(("path:/usr/bin/python",))
    assert len(rules) == 1
    assert rules[0].kind == "path"
    # 命中: 整条路径含 "/usr/bin/python"
    assert rules[0].matcher("/usr/bin/python script.py") is True
    # 不命中: 路径在 /usr/local/bin 下, basenames 一样但路径不同
    assert rules[0].matcher("/usr/local/bin/python script.py") is False


def test_compile_path_regex_with_anchors():
    """path: 支持正则锚定末尾, 区分 python3.11 vs python3.11m。"""
    rules = _compile_binary_blacklist((r"path:.*/python3\.11$",))
    assert rules[0].kind == "path"
    assert rules[0].matcher("/usr/bin/python3.11") is True
    # 末尾多一个 m → 不命中
    assert rules[0].matcher("/usr/bin/python3.11m") is False


def test_compile_path_glob_matches_full_path():
    """path-glob: fnmatch 作用于整条路径。"""
    rules = _compile_binary_blacklist(("path-glob:/usr/bin/*",))
    assert rules[0].kind == "path-glob"
    # 命中: 路径以 /usr/bin/ 开头
    assert rules[0].matcher("/usr/bin/python3.11") is True
    assert rules[0].matcher("/usr/bin/curl") is True
    # 不命中: 不同目录
    assert rules[0].matcher("/usr/local/bin/python3.11") is False
    assert rules[0].matcher("/opt/bin/curl") is False


def test_compile_path_invalid_regex_raises():
    """path: 跟 re: 一样, 非法 regex 编译期抛 ValueError。"""
    with pytest.raises(ValueError, match="非法 cmd_blacklist path-pattern"):
        _compile_binary_blacklist(("path:[unclosed",))


def test_compile_mixed_kinds_coexist():
    """五种形态 (exact / glob / re / path / path-glob) 能在同一 tuple 共存。"""
    rules = _compile_binary_blacklist((
        "wget",                              # exact
        "glob:cu*",                          # glob
        r"re:^pip\d?$",                      # re
        "path:/usr/bin/python",              # path
        "path-glob:/opt/*",                  # path-glob
    ))
    kinds = sorted(r.kind for r in rules)
    assert kinds == ["exact", "glob", "path", "path-glob", "re"]


# ---------------------------------------------------------------------------
# assert_command_allowed 端到端
# ---------------------------------------------------------------------------


def test_path_rule_blocks_specific_install(patched_settings):
    """path: 命中 → BlacklistedCommand, 文案带整条路径。"""
    patched_settings(("path:/usr/bin/python",))
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("/usr/bin/python script.py")
    msg = str(ei.value)
    # 文案契约: 含 (path) 标识, 含整条路径, 含规则原文
    assert "(path)" in msg
    assert "/usr/bin/python" in msg
    assert "path:/usr/bin/python" in msg


def test_path_rule_does_not_match_other_install(patched_settings):
    """同名 binary 在不同安装位置不应被 path: 误伤。"""
    patched_settings(("path:/usr/bin/python",))
    # /usr/local/bin/python 不应被拦
    assert assert_command_allowed("/usr/local/bin/python script.py") == \
        "/usr/local/bin/python script.py"


def test_path_regex_with_end_anchor(patched_settings):
    """path: 末尾锚定只拦精确匹配, 不会误伤同名前缀的变体。"""
    patched_settings((r"path:.*/python3\.11$",))
    # 命中
    with pytest.raises(BlacklistedCommand, match=r"\(path\)"):
        assert_command_allowed("/usr/bin/python3.11 --version")
    # 不命中 (多了一个 m 后缀)
    assert assert_command_allowed("/usr/bin/python3.11m --version") == \
        "/usr/bin/python3.11m --version"


def test_path_glob_rule(patched_settings):
    """path-glob: 路径级 fnmatch。"""
    patched_settings(("path-glob:/usr/bin/*",))
    # 命中
    with pytest.raises(BlacklistedCommand, match=r"\(path-glob\)"):
        assert_command_allowed("/usr/bin/python3.11 -c print")
    # 不命中
    assert assert_command_allowed("/usr/local/bin/python3.11 -c print") == \
        "/usr/local/bin/python3.11 -c print"


def test_basename_rule_does_not_match_full_path_layer(patched_settings):
    """无 path: 前缀的精确名规则只走 basename, 不被 path* 误伤。

    即: ``exact:python`` 跟 ``path:/usr/bin/python`` 在同一条命令上
    各自只命中自己对应的层 — 这条命令里 exact 命中, path 不命中。
    """
    # 只配 exact:python; /usr/local/bin/python 的 basename 是 python, 应命中
    patched_settings(("python",))
    with pytest.raises(BlacklistedCommand, match=r"^binary 黑名单: python$"):
        assert_command_allowed("/usr/local/bin/python script.py")


def test_path_and_basename_coexist_independently(patched_settings):
    """path* 与 basename 类规则在同一条 cmd 上独立判定。

    配置同时含 ``python`` (basename) 与 ``path:/usr/bin/python`` (path)。
    命令 ``/usr/local/bin/python x`` 的 basename == python, 但路径
    不含 /usr/bin/python → basename 层命中, path 层不命中, 总结果
    仍是 BlacklistedCommand (basename 文案)。
    """
    patched_settings(("python", "path:/usr/bin/python"))
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("/usr/local/bin/python x")
    # 命中的是 basename 层 (旧文案); 不应包含 (path) 标识
    assert "(path)" not in str(ei.value)
    assert "binary 黑名单: python" in str(ei.value)


def test_path_rule_empty_cmd_does_not_trigger(patched_settings):
    """空命令 / shlex 失败时 binary_full == "", path* 不会误命中。"""
    patched_settings(("path:/usr/bin/python",))
    # shlex 失败会让 tokens=[], binary_full=""
    assert assert_command_allowed("''") == "''"  # 不抛
    # 空字符串同样
    assert assert_command_allowed("") == ""


def test_path_rule_message_includes_target_and_source(patched_settings):
    """错误文案契约: 必须含 命中目标(整条路径) + 规则前缀原文。"""
    patched_settings((r"path:.*/evil-bin$",))
    with pytest.raises(BlacklistedCommand) as ei:
        assert_command_allowed("/opt/secret/evil-bin --bad-flag")
    msg = str(ei.value)
    # 整条路径 (含目录) 应在文案里, 不能只是 basename
    assert "/opt/secret/evil-bin" in msg
    assert "evil-bin" in msg
    # 规则原文也要在文案里, 让审批人能看到他写的那条规则
    assert r"path:.*/evil-bin$" in msg


# ---------------------------------------------------------------------------
# _DANGEROUS_PATTERNS 仍按整条 cmd 走, 不受 path 层影响
# ---------------------------------------------------------------------------


def test_path_rule_does_not_short_circuit_dangerous_pattern_layer(patched_settings):
    """path* 规则未命中时, 后续 _DANGEROUS_PATTERNS 仍要工作。"""
    # path 层完全不匹配, 但 cmd 含 sudo → 第 2 层命中
    patched_settings(("path:/no/such/binary",))
    with pytest.raises(BlacklistedCommand, match=r"危险模式命中"):
        assert_command_allowed("sudo echo hi")


# ---------------------------------------------------------------------------
# run_cmd 端到端 (通过 settings.cmd_blacklist 触发)
# ---------------------------------------------------------------------------


def test_run_cmd_end_to_end_path_rule_blocks(monkeypatch, repo_root):
    """run_cmd 走完整拦截链: path: 命中 → ok=False, error 含 (path)。"""
    # 在临时 repo 里, 直接读 settings.cmd_blacklist, 验证 run_cmd 返回值
    from xragent.tools.exec_tools import run_cmd

    reset_settings_cache()
    s = Settings(cmd_blacklist=("path:/usr/bin/python",))
    monkeypatch.setattr(settings_mod, "_settings", s, raising=False)

    result = run_cmd("/usr/bin/python -c print")
    assert result["ok"] is False
    assert "binary 黑名单" in result["error"]
    assert "(path)" in result["error"]