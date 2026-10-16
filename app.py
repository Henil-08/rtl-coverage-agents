from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from agent.llm import DEFAULT_MODEL, get_llm
from agent.service import VerificationService
from agent.state import DEFAULTS
from designs import DESIGNS, get_design

st.set_page_config(page_title="Coverage agent", layout="wide")

MODE_HELP = {
    "auto": "Agents run the whole loop, Verilator included.",
    "approval": "Pauses for your OK on the plan, the assertions, every testbench and every result.",
    "manual": "Agents write the tests; you run the generated run.sh yourself.",
}


@st.cache_resource
def get_service(model: str) -> VerificationService:
    return VerificationService(llm=get_llm(model))


def live_log():
    box = st.status("Agents working...", expanded=True)

    def on_event(e: dict) -> None:
        box.write(f"**{e['agent']}** · {e['kind']} · {e['summary']}")

    return box, on_event


with st.sidebar:
    st.header("New session")
    model = st.text_input("Groq model", os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    svc = get_service(model)
    if get_llm(model) is None:
        st.warning("GROQ_API_KEY not set: every agent uses its deterministic fallback.")

    design = st.selectbox("Design", list(DESIGNS), format_func=lambda n: DESIGNS[n].title)
    mode = st.radio("Mode", list(MODE_HELP), horizontal=True)
    st.caption(MODE_HELP[mode])
    with st.expander("Stop rule"):
        target = st.number_input("Functional target %", 1.0, 100.0, float(DEFAULTS["target_pct"]), 1.0)
        toggle_target = st.number_input("Toggle target %", 0.0, 100.0, float(DEFAULTS["toggle_target"]), 1.0)
        max_iters = st.number_input("Max iterations", 1, 30, int(DEFAULTS["max_iters"]))
        plateau_iters = st.number_input("Plateau window", 1, 10, int(DEFAULTS["plateau_iters"]))
        plateau_delta = st.number_input("Plateau min gain %", 0.0, 50.0, float(DEFAULTS["plateau_delta"]), 0.5)
    if st.button("Start", type="primary", width="stretch"):
        box, on_event = live_log()
        st_ = svc.start(design, mode, on_event=on_event, target_pct=target, toggle_target=toggle_target,
                        max_iters=max_iters, plateau_iters=plateau_iters, plateau_delta=plateau_delta)
        box.update(label="Paused for you" if st_["pending"] else "Done", state="complete")
        st.session_state["sid"] = st_["session_id"]
        st.rerun()

    sessions = svc.list_sessions()
    if sessions:
        st.divider()
        current = st.session_state.get("sid")
        picked = st.selectbox("Open session", sessions, index=sessions.index(current) if current in sessions else 0)
        if picked != current:
            st.session_state["sid"] = picked
            st.rerun()

sid = st.session_state.get("sid")
st.title("Coverage-guided verification agent")
if not sid:
    st.info("Pick a design and a mode in the sidebar, then press Start.")
    st.stop()

status = svc.status(sid)
if status["design"] not in DESIGNS:
    st.warning("This session was made by an older version of the app and cannot be opened.")
    st.stop()
d = get_design(status["design"])
res = status["result"]
code = res.get("code") or {}
st.caption(f"`{sid}` · {d.title} · {status['mode']} mode · MCP clients can use session_id=\"{sid}\"")

cols = st.columns(6)
cols[0].metric("Iteration", status["iteration"])
cols[1].metric("Functional", f"{res['functional_pct']:.1f}%" if res.get("functional_pct") is not None else "-")
for col, kind in zip(cols[2:5], ("toggle", "branch", "expr")):
    pct = (code.get(kind) or {}).get("pct")
    col.metric(kind.capitalize(), f"{pct:.1f}%" if pct is not None else "-")
active = sum(a["status"] == "active" for a in status["assertions"])
cols[5].metric("Assertions", f"{active} active", f"{len(status['assertions']) - active} dropped", delta_color="off")

if status["done"]:
    (st.error if status["issue"] == "design_mismatch" else st.success)(status["stop_reason"])
    if status["triage_note"]:
        st.markdown(f"**Triage:** {status['triage_note']}")


def respond(action: str, feedback: str = "") -> None:
    box, on_event = live_log()
    out = svc.respond(sid, action, feedback, on_event=on_event)
    box.update(label="Paused for you" if out["pending"] else "Done", state="complete")
    st.rerun()


pending = status["pending"]
if pending:
    step = pending["step"]
    with st.container(border=True):
        if step == "run_simulation":
            st.subheader(f"Your turn: run iteration {pending['iteration']}")
            st.markdown("Run this in a terminal, then press the button. Verilator writes the logs and "
                        "`coverage.dat` into the run folder and the agents read them from there.")
            st.code(pending["command"], language="bash")
            with st.expander("testbench.sv"):
                st.code(pending["testbench"], language="verilog", line_numbers=True)
            if st.button("I ran it", type="primary"):
                respond("approve")
        else:
            titles = {"plan": "Review the verification plan", "assertions": "Review the assertions",
                      "testbench": f"Review the testbench for iteration {pending['iteration']}",
                      "results": f"Review the results of iteration {pending['iteration']}"}
            st.subheader(titles[step])
            if step == "plan":
                st.dataframe(pd.DataFrame(pending["plan"]), hide_index=True, width="stretch")
            elif step == "assertions":
                st.code("\n".join(a["code"] for a in pending["assertions"]), language="verilog")
            elif step == "testbench":
                st.markdown(f"**Focus:** {pending['focus']}")
                st.code(pending["testbench"], language="verilog", line_numbers=True)
            else:
                r = pending["result"]
                st.markdown(f"**{'PASS' if r.get('passed') else 'FAIL'}** · functional {r.get('functional_pct')}%")
                st.markdown(pending["analysis"])
                if pending["done"]:
                    st.info(f"Analyst wants to stop: {pending['stop_reason']}")
            feedback = st.text_area("Feedback (for reject, or as guidance for the next test)", key=f"fb_{sid}_{step}")
            b1, b2, b3 = st.columns(3)
            if b1.button("Approve", type="primary", width="stretch"):
                respond("approve", feedback)
            if step != "results" and b2.button("Reject and redo", width="stretch"):
                respond("reject", feedback)
            if step == "results" and b3.button("Stop here", width="stretch"):
                respond("stop")

progress, plan_tab, cov_tab, tb_tab, mut_tab = st.tabs(
    ["Progress", "Plan & assertions", "Coverage", "Testbench", "Mutation testing"])

with progress:
    if status["history"]:
        hist = pd.DataFrame(status["history"]).set_index("iteration")
        chart = hist[["functional_pct", "toggle_pct"]].rename(
            columns={"functional_pct": "functional %", "toggle_pct": "toggle %"})
        st.line_chart(chart, height=260, y_label="coverage %")
    st.markdown("**Agent trace**")
    trace = pd.DataFrame(status["events"])
    if not trace.empty:
        st.dataframe(trace[["iteration", "agent", "kind", "summary"]].iloc[::-1], hide_index=True,
                     width="stretch", height=360)

with plan_tab:
    st.dataframe(pd.DataFrame(status["plan"]), hide_index=True, width="stretch")
    for a in status["assertions"]:
        st.markdown(f"`{a['label']}` · **{a['status']}**" + (f" · {a['reason']}" if a.get("reason") else ""))
        st.code(a["code"], language="verilog")

with cov_tab:
    if res.get("bins"):
        left, right = st.columns(2)
        with left:
            pts = pd.DataFrame(sorted(res["point_pct"].items()), columns=["coverpoint", "coverage %"])
            st.dataframe(pts, hide_index=True, width="stretch")
            missing = [k for k, v in res["bins"].items() if v == 0]
            st.markdown("**Uncovered bins:** " + (", ".join(f"`{m}`" for m in missing) or "none"))
        with right:
            rows = [{"kind": k, "hit": v["hit"], "total": v["total"], "%": v.get("pct")} for k, v in code.items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            for kind in ("branch", "expr", "toggle"):
                missed = (code.get(kind) or {}).get("missed", [])
                if missed:
                    with st.expander(f"missed {kind} points ({len(missed)})"):
                        st.code("\n".join(missed))
    else:
        st.info("No simulation yet.")

with tb_tab:
    if status["testbench"]:
        st.code(status["testbench"], language="verilog", line_numbers=True)
    for name, text in d.sources().items():
        with st.expander(name):
            st.code(text, language="verilog", line_numbers=True)
    if res.get("log"):
        with st.expander("last simulator log"):
            st.code(res["log"])

with mut_tab:
    st.markdown(f"{len(d.mutants)} mutants of `{d.rtl_files[0]}`. Each runs the current suite; a failing run means "
                "the mutant is caught. The table shows whether the assertions or the reference model caught it.")
    if st.button("Run mutation testing", disabled=not status["blocks"]):
        with st.spinner("Building and running every mutant..."):
            svc.run_mutation(sid)
        st.rerun()
    rep = svc.mutation_report(sid)
    if rep:
        if not rep["golden_ok"]:
            st.error(f"The suite fails on the unmodified design: {rep['golden_errors']}")
        else:
            if rep["stale"]:
                st.warning("The suite changed since this run. Run it again for a current score.")
            m1, m2, m3 = st.columns(3)
            m1.metric("Caught", f"{rep['caught']} / {rep['total']}")
            m2.metric("Caught by assertions", f"{rep['caught_by_assertions']} / {rep['total']}")
            m3.metric("Survived", ", ".join(rep["survived"]) or "none")
            st.dataframe(pd.DataFrame(rep["results"])[
                ["id", "category", "description", "verdict", "by_assertion", "by_scoreboard"]],
                hide_index=True, width="stretch")
