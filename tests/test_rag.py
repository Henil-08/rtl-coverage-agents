import pytest

from rag import kb


@pytest.fixture
def tiny_kb(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(kb, "INDEX", tmp_path / "index")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ram.md").write_text(
        "In read-first mode the output port shows the old contents of the address while new data is written. "
        "When both ports write the same address in the same clock cycle the result is a write collision and "
        "the stored value depends on port priority. " * 4)
    (tmp_path / "docs" / "uvm.html").write_text(
        "<html><script>skip()</script><p>A UVM sequence generates sequence items that a driver turns into pin "
        "activity. A monitor samples the bus and a scoreboard compares against a reference model.</p></html>" * 4)
    for i, topic in enumerate(("clock domain crossing synchronizers", "UART baud rate generation",
                                "PCIe link training states", "DDR refresh timing")):
        (tmp_path / "docs" / f"filler{i}.txt").write_text(f"Notes on {topic}. " * 40)
    kb.load.cache_clear()
    yield
    kb.load.cache_clear()


def test_build_and_keyword_search(tiny_kb):
    info = kb.build(progress=lambda *_: None, embed=False)
    assert info["docs"] == 6 and info["chunks"] >= 2 and info["embeddings"] is False
    base = kb.load()
    top = base.search("both ports write the same address collision", 1)[0]
    assert top["doc"] == "ram" and top["query"]
    assert base.search("scoreboard reference model driver", 1)[0]["doc"] == "uvm"
    assert "skip()" not in " ".join(c["text"] for c in base.chunks)


def test_planner_cites_passages_for_every_feature(tiny_kb, tmp_path):
    from agent.nodes import cite, retrieve
    from designs import get_design

    kb.build(progress=lambda *_: None, embed=False)
    d = get_design("dpram")
    hits = retrieve(d)
    assert hits and all(h["ref"].startswith("S") for h in hits)
    plan = [dict(p) for p in d.default_plan]
    hits = cite(plan, hits)
    assert all(p["sources"] for p in plan)
    refs = {h["ref"] for h in hits}
    assert all(set(p["sources"]) <= refs for p in plan)
