import subprocess

import pytest

from agent.service import VerificationService
from agent.sim import verilator_available
from designs import get_design

pytestmark = pytest.mark.skipif(not verilator_available(), reason="verilator not installed")


@pytest.fixture
def make_svc(tmp_path):
    def make(llm=None):
        return VerificationService(llm=llm, db_path=tmp_path / "s.sqlite", runs_dir=tmp_path / "runs")
    return make


def agents(st):
    return {e["agent"] for e in st["events"]}


@pytest.mark.parametrize("design", ["adder4", "dpram"])
def test_auto_mode_closes_functional_coverage(make_svc, design):
    svc = make_svc()
    st = svc.start(design, "auto", target_pct=100.0, max_iters=8)
    assert st["done"] and st["pending"] is None
    assert st["result"]["functional_pct"] == 100.0, st["stop_reason"]
    pcts = [h["functional_pct"] for h in st["history"]]
    assert pcts == sorted(pcts)
    assert {"planner", "assertion_writer", "stimulus_writer", "simulator", "triage", "coverage_analyst"} <= agents(st)
    suite = svc.suite(st["session_id"])
    for i in range(1, st["iteration"] + 1):
        assert f"stim_it{i}();" in suite


def test_approval_mode_gates_every_step(make_svc):
    svc = make_svc()
    st = svc.start("adder4", "approval", thread_id="ap")
    assert st["pending"]["step"] == "plan"
    st = svc.respond("ap", "approve")
    assert st["pending"]["step"] == "assertions"
    st = svc.respond("ap", "approve")
    assert st["pending"]["step"] == "testbench" and st["iteration"] == 1
    st = svc.respond("ap", "reject", "try the carry chain first")
    assert st["pending"]["step"] == "testbench" and st["iteration"] == 1
    st = svc.respond("ap", "approve")
    assert st["pending"]["step"] == "results" and st["result"]["built"]
    st = svc.respond("ap", "stop")
    assert st["done"] and st["stop_reason"] == "stopped by reviewer"


def test_manual_mode_waits_for_the_human_to_run(make_svc):
    svc = make_svc()
    st = svc.start("adder4", "manual", thread_id="man", max_iters=1)
    first = st["pending"]
    assert first["step"] == "run_simulation" and first["command"].startswith("bash ")
    st = svc.respond("man")
    assert st["pending"]["run_dir"] == first["run_dir"]
    subprocess.run(first["command"], shell=True, check=True, capture_output=True)
    st = svc.respond("man")
    assert st["done"] and st["result"]["functional_pct"] > 0


class FakeLLM:
    """Bad stimulus once, then good; one assertion that is wrong for a correct adder."""

    def __init__(self):
        self.stimulus_calls = 0
        self.repairs = 0

    def invoke(self, msgs):
        system, user = msgs[0][1], msgs[-1][1]
        if "verification plan" in system:
            out = '[{"feature": "sum is right", "coverpoints": ["cp_a"], "risk": "wrong sum"}]'
        elif "This assertion has a problem" in user:
            self.repairs += 1
            out = "DROP"
        elif "SystemVerilog Assertions" in system:
            out = ("<assertions>\na_sum: assert property (@(posedge clk) {cout, sum} == a + b + cin);\n"
                   "a_wrong: assert property (@(posedge clk) cout == 1'b0);\n</assertions>")
        elif "closing coverage" in system:
            self.stimulus_calls += 1
            if self.stimulus_calls == 1:
                out = "<focus>broken</focus><stimulus>apply(4'd1, 4'd2);</stimulus>"
            else:
                out = "<focus>carry</focus><stimulus>apply(4'd15, 4'd1, 1'b0);\napply(4'd0, 4'd0, 1'b0);</stimulus>"
        else:
            out = "Still missing the low x high crosses; apply a=3, b=9."
        return type("R", (), {"content": out})()


def test_triage_routes_compile_errors_and_bad_assertions(make_svc):
    llm = FakeLLM()
    svc = make_svc(llm)
    st = svc.start("adder4", "auto", thread_id="llm", max_iters=2)
    kinds = [(e["agent"], e["summary"]) for e in st["events"]]
    assert any(a == "triage" and "stimulus compile error" in s for a, s in kinds)
    assert any(a == "triage" and "a_wrong" in s for a, s in kinds)
    assert llm.repairs == 1
    status = {a["label"]: a["status"] for a in st["assertions"]}
    assert status == {"a_sum": "active", "a_wrong": "dropped"}
    assert st["result"]["passed"] is True
    assert st["plan"][0]["feature"] == "sum is right"
    assert any(e["agent"] == "coverage_analyst" and e["kind"] == "llm" for e in st["events"])
    assert st["blocks"][-1]["iteration"] == 2


def test_design_bug_stops_the_loop(make_svc, monkeypatch):
    d = get_design("adder4")
    buggy = d.mutant_sources(d.mutants[2])
    monkeypatch.setattr(type(d), "sources", lambda self: buggy)
    st = make_svc().start("adder4", "auto")
    assert st["done"] and "possible design bug" in st["stop_reason"]
    assert st["issue"] == "design_mismatch"


def test_mutation_scores(make_svc):
    svc = make_svc()
    adder = svc.start("adder4", "auto", target_pct=100.0)
    rep = svc.run_mutation(adder["session_id"])
    assert rep["golden_ok"] and rep["caught"] == 10
    dp = svc.start("dpram", "auto", target_pct=100.0)
    rep = svc.run_mutation(dp["session_id"])
    assert rep["golden_ok"] and rep["survived"] == ["M10"]
    assert svc.mutation_report(dp["session_id"])["stale"] is False
    assert svc.summary(dp["session_id"])["mutation"]["caught"] == 9


def test_report_and_bundle_cover_the_whole_session(make_svc):
    import io
    import zipfile

    from agent import report

    svc = make_svc()
    st = svc.start("dpram", "auto", thread_id="rep")
    mut = svc.run_mutation("rep")
    d = get_design("dpram")
    md = report.markdown(svc.status("rep"), d, svc.mutation_report("rep"))
    for section in ("## Summary", "## Final coverage", "## Iterations", "## Assertions", "## Mutation testing"):
        assert section in md
    assert f"Caught {mut['caught']}/10" in md
    assert all(r["wave"] for r in st["runs"])
    names = zipfile.ZipFile(io.BytesIO(report.bundle(svc.status("rep"), d, mut, svc.suite("rep")))).namelist()
    assert "report.md" in names and "testbench.sv" in names
    assert any(n.startswith("waves/run_") for n in names) and any(n.startswith("waves/mutant_") for n in names)


def test_uvm_session_runs_end_to_end(make_svc):
    from pathlib import Path

    if not (Path(__file__).resolve().parent.parent / "third_party/uvm/src/uvm_pkg.sv").exists():
        pytest.skip("UVM submodule missing")
    st = make_svc().start("adder4", "auto", language="uvm", max_iters=2)
    assert st["language"] == "uvm" and st["result"]["built"]
    assert "class seq_it1 extends base_seq" in st["testbench"]
    assert st["result"]["functional_pct"] > 90


def test_live_events_stream_tokens_nodes_and_simulator_output(make_svc):
    class StreamingLLM(FakeLLM):
        def stream(self, msgs):
            text = self.invoke(msgs).content
            for i in range(0, len(text), 7):
                yield type("C", (), {"content": text[i:i + 7]})()

    seen = []
    make_svc(StreamingLLM()).start("adder4", "auto", thread_id="live", max_iters=1, on_event=seen.append)
    kinds = {e["type"] for e in seen}
    assert {"node_start", "node_done", "token", "llm_start", "llm_end", "sim_line", "finished"} <= kinds
    planner_text = "".join(e["text"] for e in seen if e["type"] == "token" and e["agent"] == "planner")
    assert '"sum is right"' in planner_text
    done = [e for e in seen if e["type"] == "node_done" and e["node"] == "simulator"]
    assert done and "log" not in done[0]["update"]["result"]
    assert any("TEST PASSED" in e["text"] for e in seen if e["type"] == "sim_line")


class ArchitectLLM(FakeLLM):
    """Plays the testbench architect by handing back a known-good testbench, after one broken attempt."""

    def __init__(self, design="adder4", lang="sv"):
        super().__init__()
        self.tb = get_design(design).template(lang)
        self.sv = get_design(design).template("sv")
        self.arch_calls = 0

    def invoke(self, msgs):
        user = msgs[-1][1]
        if "Write the testbench TEMPLATE" in user:
            self.arch_calls += 1
            body = self.sv if "PREVIOUS TESTBENCH FAILED" in user else self.sv.replace("// @STIMULUS_CALLS", "")
            out = (f"<testbench>\n{body}\n</testbench>\n<how_to_drive>apply(a, b, cin): one vector per cycle"
                   f"</how_to_drive>\n<wave_signals>a, b, cin, sum, exp_sum, cout, exp_cout</wave_signals>")
            return type("R", (), {"content": out})()
        if "equivalent UVM testbench" in user:
            return type("R", (), {"content": f"<testbench>\n{self.tb}\n</testbench>"})()
        return super().invoke(msgs)


def test_generated_testbench_passes_gates_and_drives_the_loop(make_svc):
    llm = ArchitectLLM()
    svc = make_svc(llm)
    seen = []
    st = svc.start("adder4", "auto", thread_id="gen", tb_source="generated", max_iters=2, on_event=seen.append)
    gen = st["gen_tb"]
    assert gen["ok"] and llm.arch_calls == 2
    gates = [(g["gate"], g["ok"]) for g in gen["gates"]]
    assert gates[0] == ("structure", False)
    assert ("compile", True) in gates and ("golden_run", True) in gates and ("mutant_smoke", True) in gates
    assert [t["name"] for t in gen["drivers"]] == ["apply"]
    assert any(e["type"] == "tb_gate" for e in seen)
    assert st["result"]["built"] and st["result"]["functional_pct"] > 50
    assert "stim_it1" in svc.suite("gen")


def test_uploaded_design_requires_generation_and_llm(make_svc, tmp_path, monkeypatch):
    from designs import user

    monkeypatch.setattr(user, "USER_DIR", tmp_path / "ud")
    user.create("adder_copy", get_design("adder4").sources(), get_design("adder4").spec())
    st = make_svc().start("adder_copy", "auto", thread_id="nollm")
    assert st["done"] and st["issue"] == "tb_failed" and "needs an LLM" in st["stop_reason"]
    st = make_svc(ArchitectLLM()).start("adder_copy", "auto", thread_id="up", max_iters=1)
    assert st["tb_source"] == "generated" and st["gen_tb"]["ok"] and st["result"]["built"]


def test_generated_uvm_testbench(make_svc):
    from pathlib import Path

    if not (Path(__file__).resolve().parent.parent / "third_party/uvm/src/uvm_pkg.sv").exists():
        pytest.skip("UVM submodule missing")
    st = make_svc(ArchitectLLM("adder4", "uvm")).start("adder4", "auto", thread_id="genuvm", language="uvm",
                                                        tb_source="generated", max_iters=1)
    gates = {g["gate"]: g["ok"] for g in st["gen_tb"]["gates"]}
    assert gates["uvm_compile"] and gates["uvm_golden_run"] and gates["uvm_matches_sv"]
    assert st["language"] == "uvm" and "class seq_it1 extends base_seq" in st["testbench"]
    assert st["result"]["built"]


def test_per_agent_model_overrides(make_svc, monkeypatch):
    import agent.nodes as nodes

    calls = []

    class Named(FakeLLM):
        def __init__(self, name):
            super().__init__()
            self.name = name

        def invoke(self, msgs):
            calls.append((self.name, msgs[0][1]))
            return super().invoke(msgs)

    small, big = Named("small"), Named("big")
    monkeypatch.setattr(nodes, "get_llm", lambda ref: {"ollama:small": small, "anthropic:big": big}.get(ref))
    st = make_svc(FakeLLM()).start("adder4", "auto", thread_id="route", max_iters=1, model="ollama:small",
                                   agent_models={"planner": "anthropic:big"})
    who = {n for n, system in calls if "verification lead. You turn" in system}
    assert who == {"big"}
    assert any(n == "small" for n, _ in calls)
    assert st["model"] == "ollama:small" and st["agent_models"] == {"planner": "anthropic:big"}
    with pytest.raises(ValueError):
        make_svc().start("adder4", "auto", model="nonsense")


def test_mcp_brain_answers_every_agent_step(make_svc):
    brain = FakeLLM()
    svc = make_svc()
    st = svc.start("adder4", "auto", thread_id="brain", model="mcp:claude", max_iters=1)
    agents = []
    for _ in range(30):
        task = st["pending"]
        if not task:
            break
        assert task["step"] == "llm_task"
        agents.append(task["agent"])
        reply = brain.invoke([("system", task["system"]), ("user", task["prompt"])]).content
        st = svc.respond("brain", "answer", reply)
    assert st["done"] and st["result"]["built"]
    assert agents[:3] == ["planner", "assertion_writer", "stimulus_writer"]
    assert st["plan"][0]["feature"] == "sum is right"
