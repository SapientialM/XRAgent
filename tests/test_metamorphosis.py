"""金蝉脱壳主流程。"""
from __future__ import annotations

from xragent.evolve.generations import append_generation, list_generations
from xragent.evolve.metamorphosis import metamorphose


def test_metamorphose_returns_compile_results(repo_root):
    # 在 repo_root 放几个 .py 文件让 py_compile 跑
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    (src / "b.py").write_text("y = 2 # syntax error\n" if False else "y = 2\n", encoding="utf-8")

    res = metamorphose("test metamorphose")
    assert "ok" in res
    assert "compile_results" in res
    assert "generation" in res
    assert res["head_after"] is not None


def test_metamorphose_records_generation(repo_root):
    src = repo_root / "src"
    src.mkdir(exist_ok=True)
    (src / "ok.py").write_text("ok = True\n", encoding="utf-8")
    metamorphose("first gen")
    gens = list_generations()
    assert len(gens) == 1
    assert gens[0]["reason"] == "first gen"


def test_append_generation_persists(repo_root):
    append_generation("aaa", "bbb", "unit test", {"compile_ok": True})
    append_generation("ccc", "ddd", "unit test 2")
    gens = list_generations()
    assert len(gens) == 2
    assert gens[0]["reason"] == "unit test"  # append 顺序：先写先读
