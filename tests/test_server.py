import time

import pytest
from fastapi.testclient import TestClient

from agent.service import VerificationService
from agent.sim import verilator_available
from designs import user
from server import app as server

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_svc", VerificationService(db_path=tmp_path / "s.sqlite", runs_dir=tmp_path / "runs"))
    monkeypatch.setattr(user, "USER_DIR", tmp_path / "ud")
    with TestClient(server.app) as c:
        yield c


def wait_idle(client, sid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/sessions/{sid}").json()
        if not st.get("running"):
            return st
        time.sleep(0.5)
    raise TimeoutError


def test_designs_and_config(client):
    names = {d["name"] for d in client.get("/api/designs").json()}
    assert {"dpram", "adder4"} <= names
    d = client.get("/api/designs/dpram").json()
    assert d["ports"]["clock"] == "clk" and "R6" in d["spec"] and len(d["mutants"]) == 10
    assert client.get("/api/config").json()["verilator"] is True


def test_live_session_over_websocket(client):
    sid = client.post("/api/sessions", json={"design": "adder4", "mode": "auto", "max_iters": 2}).json()["session_id"]
    seen = []
    with client.websocket_connect(f"/api/sessions/{sid}/live") as ws:
        while True:
            e = ws.receive_json()
            seen.append(e["type"])
            if e["type"] == "idle":
                break
    assert "node_start" in seen and "sim_line" in seen and "finished" in seen
    st = wait_idle(client, sid)
    assert st["done"] and st["result"]["functional_pct"] > 90
    w = client.get(f"/api/sessions/{sid}/wave").json()
    assert w["total_cycles"] > 0 and w["diagram"]["signal"]
    assert client.get(f"/api/sessions/{sid}/report.md").text.startswith("# Verification report")
    assert client.post(f"/api/sessions/{sid}/mutation").json()["ok"]
    st = wait_idle(client, sid)
    assert st["mutation"]["caught"] == 10
    assert client.get(f"/api/sessions/{sid}/wave", params={"mutant": "M01"}).json()["failures"]


def test_approval_respond_and_upload(client):
    sid = client.post("/api/sessions", json={"design": "adder4", "mode": "approval"}).json()["session_id"]
    st = wait_idle(client, sid)
    assert st["pending"]["step"] == "plan"
    assert client.post(f"/api/sessions/{sid}/respond", json={"action": "approve"}).json()["ok"]
    assert wait_idle(client, sid)["pending"]["step"] == "assertions"

    rtl = "module inv(input logic clk, input logic a, output logic y);\nalways_ff @(posedge clk) y <= ~a;\nendmodule\n"
    r = client.post("/api/designs", data={"name": "inv", "title": "Registered inverter"},
                    files=[("rtl_files", ("inv.sv", rtl)), ("spec_file", ("spec.md", "- R1: y is not a, one cycle later"))])
    assert r.status_code == 200, r.text
    assert client.get("/api/designs/inv").json()["ports"]["top"] == "inv"
    bad = client.post("/api/designs", data={"name": "Bad Name"},
                      files=[("rtl_files", ("x.sv", rtl)), ("spec_file", ("spec.md", "x"))])
    assert bad.status_code == 400
