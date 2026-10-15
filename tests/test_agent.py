from __future__ import annotations

import pytest

from agent.fallback import ALL_BINS, bins_hit
from agent.nodes import _parse_generation
from agent.parser import parse_report
from agent.service import VerificationService
from agent.tb_template import COVERAGE_MODEL, build_testbench, dut_source
from mutation.mutants import MUTANTS, verdict
from tests.fake_sim import simulate


@pytest.fixture
def svc(tmp_path):
    return VerificationService(llm=None, db_path=tmp_path / "s.sqlite")


def test_python_mirror_bins_are_in_model():
    hit = set()
    for a in range(16):
        for b in range(16):
            for c in range(2):
                hit |= bins_hit(a, b, c)
    assert hit == ALL_BINS


def test_parser_markers_and_bins():
    log = simulate("apply(4'd0, 4'd0, 1'b0);\napply(4'd15, 4'd15, 1'b1);")
    p = parse_report(log)
    assert p["passed"] is True
    assert p["coverage_pct"] is not None
    assert set(p["point_pct"]) == set(COVERAGE_MODEL)
    assert p["bins"]["cp_a.zero"] is True
    assert p["bins"]["cp_a.low"] is False
    assert p["bins"]["cx_a_b.maxxmax"] is True
    assert p["bins"]["cx_a_b.zeroxmax"] is False


def test_parser_failures():
    p = parse_report(simulate("apply(4'd15, 4'd1, 1'b0);", fail_check=True))
    assert p["passed"] is False and p["check_failures"]
    p = parse_report("# KERNEL: ASSERT_FAIL a_it2_carry at time 25\n# KERNEL: TEST FAILED")
    assert p["assertion_failures"] and p["passed"] is False
    p = parse_report("# COMP96 ERROR: testbench.sv(12): Error: syntax error")
    assert p["passed"] is None and p["coverage_pct"] is None


def test_parse_generation_relabels_and_rejects():
    ok = _parse_generation(
        "<focus>carry</focus><assertions>\nchk: assert property (@(posedge clk) 1) else begin end\n</assertions>"
        "<stimulus>\napply(4'd15, 4'd1, 1'b0);\n</stimulus>",
        3,
    )
    assert ok and "a_it3_chk: assert" in ok["assertions"]
    assert _parse_generation("<stimulus>$finish;</stimulus>", 1) is None


def test_full_loop_reaches_target(svc):
    st = svc.start("t1", target_pct=100.0, max_iters=8, plateau_iters=2)
    assert st["pending"] and st["iteration"] == 1
    assert "module tb" in st["pending"]["testbench"]
    seen = []
    while not st["done"]:
        st = svc.submit_report("t1", simulate(st["pending"]["testbench"]))
        seen.append(st["coverage_pct"])
    assert seen == sorted(seen)
    assert st["coverage_pct"] == 100.0
    assert "target" in st["stop_reason"]
    tb = svc.suite_testbench("t1")
    for i in range(1, st["iteration"] + 1):
        assert f"stim_it{i}();" in tb


def test_garbage_paste_reprompts(svc):
    svc.start("t2")
    st = svc.submit_report("t2", "hello")
    assert st["pending"]["parse_error"] and st["iteration"] == 1 and not st["history"]


def test_plateau_stop(svc):
    st = svc.start("t3", target_pct=100.0, plateau_iters=2, max_iters=10)
    tb = st["pending"]["testbench"]
    first = simulate(tb)
    st = svc.submit_report("t3", first)
    for _ in range(5):
        if st["done"]:
            break
        st = svc.submit_report("t3", first)
    assert st["done"] and "plateau" in st["stop_reason"]


def test_mutants_apply_and_differ():
    golden = dut_source()
    srcs = {m.id: m.source(golden) for m in MUTANTS}
    assert len(srcs) == 10 and len(set(srcs.values())) == 10
    for s in srcs.values():
        assert "module adder4" in s and "logic [4:0] c;" in s


def test_mutation_scoring(svc):
    st = svc.start("t4")
    svc.submit_report("t4", simulate(st["pending"]["testbench"]))
    tb = svc.suite_testbench("t4")
    r = svc.submit_mutation("t4", "M03", simulate(tb, fail_check=True))
    assert r["verdict"] == "caught" and r["score"]["caught"] == 1
    r = svc.submit_mutation("t4", "M07", simulate(tb))
    assert r["verdict"] == "survived" and r["score"]["run"] == 2
    assert verdict({"passed": None}) == "invalid"


def test_harness_formats():
    tb = build_testbench(1, [{"iteration": 1, "focus": "x", "stimulus": "apply(4'd0, 4'd0, 1'b0);", "assertions": ""}])
    assert "{cout, sum} !== exp_full" in tb and "{" not in tb.split("COV_TOTAL")[1].split("\n")[0].replace("%0.2f", "")


def test_loop_without_bin_level_report(svc):
    st = svc.start("t5", target_pct=100.0, max_iters=10)
    while not st["done"]:
        st = svc.submit_report("t5", simulate(st["pending"]["testbench"], with_bins=False))
    assert st["coverage_pct"] == 100.0


class FakeLLM:

    def __init__(self):
        self.calls = 0

    def invoke(self, msgs):
        self.calls += 1
        text = msgs[-1][1] if isinstance(msgs, list) else msgs
        if "OUTPUT exactly these three tagged sections" in text:
            body = (
                "<focus>full ripple and max+max</focus>\n<assertions>\n"
                "ripple: assert property (@(posedge clk) (a == 4'd15 && b == 4'd0 && cin) |-> cout) "
                'else begin $error("ASSERT_FAIL ripple"); errors++; end\n</assertions>\n'
                "<stimulus>\n```systemverilog\napply(4'd15, 4'd0, 1'b1);\napply(4'd15, 4'd15, 1'b1);\n```\n</stimulus>"
            )
        else:
            body = "Still missing low+high crosses; apply a=3 b=9 cin=0."
        return type("R", (), {"content": body})()


def test_llm_generation_path(tmp_path):
    llm = FakeLLM()
    svc = VerificationService(llm=llm, db_path=tmp_path / "l.sqlite")
    st = svc.start("t6")
    p = st["pending"]
    assert p["generator"] == "llm" and "a_it1_ripple: assert" in p["testbench"]
    assert "```" not in p["testbench"]
    st = svc.submit_report("t6", simulate(p["testbench"]))
    assert "a=3 b=9" in st["next_focus"] and st["iteration"] == 2
