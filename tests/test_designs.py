import random

import pytest

from agent.sim import simulate, verilator_available
from designs import DESIGNS
from designs.base import dedupe_labels, split_assertions, valid_stimulus

needs_verilator = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


@pytest.mark.parametrize("name", sorted(DESIGNS))
def test_mutants_apply_and_differ(name):
    d = DESIGNS[name]
    golden = d.sources()
    seen = set()
    for m in d.mutants:
        src = d.mutant_sources(m)
        assert src != golden
        seen.add(tuple(sorted(src.items())))
    assert len(seen) == len(d.mutants) == 10


def test_split_assertions_adds_action_block_and_dedupes():
    got = split_assertions(
        "```systemverilog\na_x: assert property (@(posedge clk)\n  a |-> b);\n"
        "a_y: assert property (@(posedge clk) 1) else $error(\"y\");\n$finish;\n```"
    )
    assert [a["label"] for a in got] == ["a_x", "a_y"]
    assert 'ASSERT_FAIL a_x' in got[0]["code"] and "errors++" in got[0]["code"]
    assert "ASSERT_FAIL" not in got[1]["code"]
    renamed = dedupe_labels(split_assertions("a_x: assert property (@(posedge clk) 1);"), got)
    assert renamed[0]["label"] == "a_x_2" and "a_x_2:" in renamed[0]["code"]


def test_valid_stimulus():
    assert valid_stimulus("apply(4'd1, 4'd2, 1'b0);", ("apply",))
    assert valid_stimulus("write_a(4'd1, 8'h00);", ("cycle", "write_a"))
    assert not valid_stimulus("apply(4'd1, 4'd2, 1'b0); #5;", ("apply",))
    assert not valid_stimulus("initial apply(1,2,0);", ("apply",))
    assert not valid_stimulus("$display(1);", ("apply",))


@needs_verilator
@pytest.mark.parametrize("name", sorted(DESIGNS))
def test_default_suite_passes_on_golden_design(name, tmp_path):
    d = DESIGNS[name]
    focus, stim = d.fallback(1, {}, [])
    tb = d.build_testbench(
        [{"iteration": 1, "focus": focus, "stimulus": stim}], split_assertions(d.default_assertions)
    )
    r = simulate(tmp_path, d.sources(), tb, d.dut_hier)
    assert r.built, r.compile_errors
    assert r.passed is True, r.log[-2000:]
    assert r.functional_pct and r.functional_pct > 50
    assert r.code["toggle"]["total"] > 0


@needs_verilator
@pytest.mark.parametrize("name", sorted(DESIGNS))
def test_random_stimulus_compiles(name, tmp_path):
    d = DESIGNS[name]
    tb = d.build_testbench([{"iteration": 1, "focus": "random", "stimulus": d.random_stimulus(random.Random(0), 20)}], [])
    r = simulate(tmp_path, d.sources(), tb, d.dut_hier)
    assert r.built and r.passed is True, r.compile_errors or r.log[-2000:]


@needs_verilator
def test_adder_python_model_matches_verilator(tmp_path):
    from designs.adder4 import ALL_BINS, DESIGN, bins_hit

    vectors = [(0, 0, 0), (15, 15, 1), (7, 1, 0), (8, 8, 0), (3, 12, 1)]
    stim = "\n".join(f"apply(4'd{a}, 4'd{b}, 1'b{c});" for a, b, c in vectors)
    r = simulate(tmp_path, DESIGN.sources(), DESIGN.build_testbench([{"iteration": 1, "stimulus": stim}], []))
    assert set(r.bins) == ALL_BINS
    expected = set().union(*(bins_hit(*v) for v in vectors))
    assert {k for k, v in r.bins.items() if v} == expected


@needs_verilator
def test_dpram_fallback_closes_functional_coverage(tmp_path):
    from designs.dpram import DESIGN

    blocks, bins, code = [], {}, None
    for it in range(1, 6):
        focus, stim = DESIGN.fallback(it, bins, blocks, code)
        blocks.append({"iteration": it, "focus": focus, "stimulus": stim})
        r = simulate(tmp_path / str(it), DESIGN.sources(), DESIGN.build_testbench(blocks, []))
        assert r.passed is True, r.compile_errors or r.check_failures
        bins, code = r.bins, r.code
    assert r.functional_pct == 100.0
    assert r.code["toggle"]["pct"] > 90


@needs_verilator
def test_dpram_reference_model_and_assertions_catch_mutants(tmp_path):
    from designs.dpram import DESIGN, LIBRARY, TOGGLE_MARCH

    stim = "\n".join(s for _, _, s in LIBRARY) + "\n" + TOGGLE_MARCH
    tb = DESIGN.build_testbench([{"iteration": 1, "stimulus": stim}], split_assertions(DESIGN.default_assertions))
    golden = simulate(tmp_path / "golden", DESIGN.sources(), tb)
    assert golden.passed is True, golden.assertion_failures or golden.check_failures
    survivors = []
    for m in DESIGN.mutants:
        r = simulate(tmp_path / m.id, DESIGN.mutant_sources(m), tb)
        assert r.built, (m.id, r.compile_errors)
        if r.passed:
            survivors.append(m.id)
    assert survivors == ["M10"]
