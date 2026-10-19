import random

import pytest

from agent.sim import verilator_available
from designs import all_designs, get_design, user
from designs.generic import driver_tasks, random_stimulus_for

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")

COUNTER = """module counter #(parameter int W = 4) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         en,
    output logic [W-1:0] q,
    output logic         wrap
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= '0;
        else if (en) q <= q + 1'b1;
    end
    assign wrap = en && (q == {W{1'b1}});
endmodule
"""
SPEC = "# Counter\n\n- R1: q counts up by one on each clock with en = 1.\n- R2: q holds when en = 0.\n- R3: wrap is 1 when en = 1 and q is all ones.\n"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(user, "USER_DIR", tmp_path)
    return tmp_path


def test_upload_creates_a_design_with_ports_and_mutants(store):
    d = user.create("counter", {"src/counter.sv": COUNTER}, SPEC, title="Up counter")
    assert d.kind == "upload" and d.title == "Up counter"
    assert d.extra["top"] == "counter" and d.extra["clock"] == "clk" and d.extra["reset"] == "rst_n"
    assert {p["name"] for p in d.extra["ports"]} == {"clk", "rst_n", "en", "q", "wrap"}
    assert d.sources() == {"rtl/counter.sv": COUNTER}
    assert len(d.mutants) >= 5 and all(m.file == "rtl/counter.sv" for m in d.mutants)
    for m in d.mutants:
        assert d.mutant_sources(m)["rtl/counter.sv"] != COUNTER
    assert [p["feature"][:3] for p in d.default_plan] == ["R1:", "R2:", "R3:"]
    assert not d.has_handwritten_tb() and d.languages() == ["sv", "uvm"]
    assert "counter" in all_designs() and get_design("counter").title == "Up counter"
    with pytest.raises(FileNotFoundError):
        d.template()


def test_upload_rejects_bad_input(store):
    with pytest.raises(ValueError):
        user.create("dpram", {"x.sv": COUNTER}, SPEC)
    with pytest.raises(ValueError):
        user.create("ok_name", {"x.txt": COUNTER}, SPEC)
    with pytest.raises(Exception):
        user.create("broken", {"x.sv": "module x(input a); assign b = ; endmodule"}, SPEC)


def test_driver_tasks_are_read_from_any_testbench():
    tasks = driver_tasks(get_design("adder4").template())
    assert tasks == [{"name": "apply", "args": [{"name": "ia", "width": 4}, {"name": "ib", "width": 4}, {"name": "ic", "width": 1}]}]
    stim = random_stimulus_for(tasks)(random.Random(0), 3)
    assert stim.count("apply(4'd") == 3
