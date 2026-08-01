"""锁定 fs_tools 的 OSError 兜底契约。

2026-07-28 round：把 read_file / list_dir / write_file 的 OSError 兜底从
"上抛异常" 改为 "返回 ok=False dict"。这是工具对外契约的修复
（之前 PermissionError 等会破坏 "always returns dict" 的承诺），但确实是
*行为变更* —— 用以下测试固定下来：

* read_file 遇到 OSError → ok=False + error 含 "读取失败"
* write_file 遇到 OSError（mkdir / write_text） → ok=False + error 含 "写入失败"
* list_dir 遇到 OSError (iterdir) → ok=False + error 含 "列出失败"

通过 monkeypatch target.read_text / target.write_text / Path.iterdir 让它们抛 OSError，
避免依赖真实文件系统权限。
"""
from __future__ import annotations

from pathlib import Path

from xragent.tools import fs_tools
from xragent.tools.fs_tools import list_dir, read_file, write_file


def test_read_file_returns_ok_false_on_oserror(repo_root: Path, monkeypatch):
    """read_text 抛 PermissionError → 返回 ok=False 而非上抛。

    用 monkeypatch 替换 Path.read_text 比真去 chmod 一个文件靠谱得多，
    既不需要 root、也不会被 macOS 的 SIP 干扰。
    """
    f = repo_root / "sandbox" / "locked.txt"
    f.write_text("secret", encoding="utf-8")

    def boom(self, *args, **kwargs):  # noqa: ARG001
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_text", boom)

    out = read_file("sandbox/locked.txt")
    assert out["ok"] is False
    assert "读取失败" in out["error"]
    assert "Permission denied" in out["error"]


def test_write_file_returns_ok_false_when_write_text_raises(repo_root: Path, monkeypatch):
    """write_text 抛 OSError → ok=False 而非上抛。"""
    real_write_text = Path.write_text

    def boom(self, *args, **kwargs):  # noqa: ARG001
        # 只对 sandbox/locked 抛错；其他正常
        if "locked" in str(self):
            raise PermissionError(13, "Permission denied", str(self))
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)

    out = write_file("sandbox/locked.txt", "data")
    assert out["ok"] is False
    assert "写入失败" in out["error"]
    assert "Permission denied" in out["error"]


def test_write_file_returns_ok_false_when_mkdir_raises(repo_root: Path, monkeypatch):
    """mkdir 抛 OSError → ok=False。"""
    def boom(self, *args, **kwargs):  # noqa: ARG001
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "mkdir", boom)

    out = write_file("sandbox/some/new.txt", "data")
    assert out["ok"] is False
    assert "写入失败" in out["error"]


def test_list_dir_returns_ok_false_when_iterdir_raises(repo_root: Path, monkeypatch):
    """iterdir 抛 PermissionError → ok=False + error 含 "列出失败"。

    跟 read_file / write_file 同套路：``Path.iterdir`` 抛 OSError 时不能
    把异常冒到 LLM 层；LLM 看到的应该是 ``{"ok": False, "error": ...}``。
    """
    target = repo_root / "sandbox"
    target.mkdir(exist_ok=True)

    def boom(self, *args, **kwargs):  # noqa: ARG001
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "iterdir", boom)

    out = list_dir("sandbox")
    assert out["ok"] is False
    assert "列出失败" in out["error"]
    assert "Permission denied" in out["error"]


def test_list_dir_unchanged_on_oserror_free_path(repo_root: Path):
    """回归：正常路径下 list_dir 仍 ok=True（防止我加兜底时把正常路径也吃了）。"""
    (repo_root / "sandbox" / "x.txt").write_text("x", encoding="utf-8")
    out = list_dir("sandbox")
    assert out["ok"] is True
    # 确保模块级 fs_tools 没意外被换掉
    assert fs_tools.read_file is read_file

def test_io_fail_helper_formats_error_uniformly():
    """``_io_fail`` 必须严格对齐 ``"<prefix>: <type_name>: <msg>"`` 契约。

    三个 fs 工具 (read_file / list_dir / write_file) 都走这个 helper 拼
    OSError 错误文案。如果未来有人在 helper 里改格式 (比如把 ``:`` 换
    成 ``-``, 或者把 type name 砍掉), LLM 在日志里 grep 的锚点
    ("读取失败: PermissionError") 就会失效 —— 这个测试守这一契约。
    """
    err = fs_tools._io_fail("读取失败", PermissionError(13, "Permission denied", "/x"))
    assert err == {
        "ok": False,
        "error": "读取失败: PermissionError: [Errno 13] Permission denied: '/x'",
    }


def test_io_fail_helper_propagates_ok_false():
    """返回字典必须 ok=False, 不能误返 ok=True 让 LLM 以为成功。"""
    out = fs_tools._io_fail("写入失败", OSError(28, "No space left on device"))
    assert out["ok"] is False
    assert "写入失败" in out["error"]


def test_io_fail_helper_uses_subclass_name_not_oserror():
    """``type(exc).__name__`` 必须反映 *实际* 子类, 不能被退化成 "OSError"。

    之前 inline 版本写 ``type(e).__name__`` 是对的, 但 helper 化之后
    有人可能图省事写成 ``"OSError"`` 字面量 —— 这个测试守类型保真。
    """
    class FakeQuotaError(OSError):
        pass
    out = fs_tools._io_fail("写入失败", FakeQuotaError("quota exceeded"))
    assert "FakeQuotaError" in out["error"], out
    # 且必须不是字面量 "OSError" 占位
    assert "OSError:" not in out["error"] or out["error"].count(":") >= 2


def test_io_fail_helper_does_not_swallow_message():
    """原 ``e`` 消息必须出现在 error 字符串里 (LLM 要看的诊断信息)。"""
    out = fs_tools._io_fail("列出失败", FileNotFoundError(2, "No such file or directory", "/y"))
    assert "No such file or directory" in out["error"], out
