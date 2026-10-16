from pathlib import Path

import pytest

from agent.sim import collect, simulate, verilator_available

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")

ADDER = (Path(__file__).resolve().parent.parent / "rtl" / "adder4.sv").read_text()

TB = """\
module tb;
  logic [3:0] a, b, sum;
  logic cin, cout, overflow;
  logic clk = 0;
  int errors = 0;
  adder4 dut (.*);
  always #5 clk = ~clk;
  covergroup cg;
    cp_a: coverpoint a { bins zero = {0}; bins max = {15}; }
    cp_cin: coverpoint cin { bins c0 = {0}; bins c1 = {1}; }
  endgroup
  cg c = new();
  a_sum: assert property (@(posedge clk) {cout, sum} == a + b + cin)
    else begin $error("ASSERT_FAIL a_sum"); errors++; end
  initial begin
    a = 0; b = 0; cin = 0;
    @(negedge clk); c.sample();
    a = 15; b = 1; @(negedge clk); c.sample();
    if (errors == 0) $display("TEST PASSED"); else $display("TEST FAILED");
    $finish;
  end
endmodule
"""


def test_passing_run_reports_coverage(tmp_path):
    r = simulate(tmp_path, {"design.sv": ADDER}, TB)
    assert r.built and r.passed is True and not r.assertion_failures
    assert r.bins == {"cp_a.zero": 1, "cp_a.max": 1, "cp_cin.c0": 2, "cp_cin.c1": 0}
    assert r.point_pct == {"cp_a": 100.0, "cp_cin": 50.0}
    assert r.functional_pct == 75.0
    tog = r.code["toggle"]
    assert tog["total"] > 0 and 0 < tog["pct"] < 100
    assert any("cin" in m for m in tog["missed"])
    assert (tmp_path / "run.sh").exists()


def test_assertion_failure_does_not_abort(tmp_path):
    broken = ADDER.replace("assign cout     = c[4];", "assign cout     = 1'b0;")
    r = simulate(tmp_path, {"design.sv": broken}, TB)
    assert r.passed is False
    assert r.assertion_failures == ["a_sum"]
    assert r.bins


def test_compile_error_is_reported(tmp_path):
    r = simulate(tmp_path, {"design.sv": ADDER}, TB.replace("cg c = new();", "cg c = new()"))
    assert not r.built and r.compile_errors
    assert r.passed is None


def test_collect_reads_manual_run(tmp_path):
    simulate(tmp_path, {"design.sv": ADDER}, TB)
    again = collect(tmp_path)
    assert again.passed is True and again.functional_pct == 75.0
