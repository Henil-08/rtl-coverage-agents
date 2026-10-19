import pytest

from agent.service import VerificationService
from agent.sim import verilator_available
from mcp_server import server

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


@pytest.fixture(autouse=True)
def isolated_service(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_svc", VerificationService(db_path=tmp_path / "s.sqlite", runs_dir=tmp_path / "runs"))


def test_simulate_tool_runs_external_stimulus():
    out = server.simulate("dpram", "write_a(4'd1, 8'hAA);\nread_b(4'd1);",
                          "a_hold_b: assert property (@(posedge clk) !en_b |=> $stable(rdata_b));")
    assert out["built"] and out["passed"]
    assert 0 < out["functional_pct"] < 100 and out["uncovered_bins"]
    assert set(out["code_coverage"]) == {"line", "branch", "toggle", "expr"}


def test_session_tools_walk_the_approval_gates():
    st = server.start_session("adder4", "approval")
    assert st["waiting_for"]["step"] == "plan"
    while not st["done"]:
        st = server.respond(st["session_id"])
    assert st["result"]["functional_pct"] == 100.0
    assert server.run_mutation_testing(st["session_id"])["caught"] == 10


def test_upload_tool(tmp_path, monkeypatch):
    from designs import user

    monkeypatch.setattr(user, "USER_DIR", tmp_path / "ud")
    rtl = "module inv(input logic clk, input logic a, output logic y);\nalways_ff @(posedge clk) y <= ~a;\nendmodule\n"
    out = server.upload_design("inv", {"inv.sv": rtl}, "- R1: y is not a, one cycle later")
    assert out["name"] == "inv" and {p["name"] for p in out["ports"]} == {"clk", "a", "y"}
