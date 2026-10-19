import pytest

from agent.rtl import RtlError, lint, ports
from agent.sim import verilator_available
from designs import get_design

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


def test_reads_dpram_ports():
    info = ports(get_design("dpram").sources())
    assert info["top"] == "dpram" and info["clock"] == "clk" and info["reset"] is None
    by_name = {p["name"]: p for p in info["ports"]}
    assert by_name["addr_a"] == {"name": "addr_a", "dir": "input", "width": 4}
    assert by_name["rdata_b"]["dir"] == "output" and by_name["rdata_b"]["width"] == 8
    assert len(info["ports"]) == 11


def test_reads_combinational_adder():
    info = ports(get_design("adder4").sources())
    assert info["top"] == "adder4" and info["clock"] is None
    assert [p["name"] for p in info["ports"]] == ["a", "b", "cin", "sum", "cout", "overflow"]


def test_reset_detection_and_errors():
    rtl = "module cnt(input logic clk, input logic rst_n, output logic [7:0] q);\n" \
          "always_ff @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else q <= q + 1;\nendmodule\n"
    info = ports({"cnt.sv": rtl})
    assert info["clock"] == "clk" and info["reset"] == "rst_n"
    assert lint({"bad.sv": "module bad(input a); assign b = ; endmodule"})
    with pytest.raises(RtlError):
        ports({"bad.sv": "module bad(input a); assign b = ; endmodule"})
