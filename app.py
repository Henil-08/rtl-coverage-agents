from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from agent.llm import DEFAULT_MODEL, get_llm
from agent.service import VerificationService
from agent.state import DEFAULTS

st.set_page_config(page_title="Coverage Agent - adder4", layout="wide")


@st.cache_resource
def get_service(model: str) -> VerificationService:
    return VerificationService(llm=get_llm(model))


with st.sidebar:
    st.header("Session")
    model = st.text_input("Groq model", os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    svc = get_service(model)
    if get_llm(model) is None:
        st.warning("GROQ_API_KEY not set: using deterministic fallback generator.")
    else:
        st.caption(f"LLM: {model}")

    sessions = svc.list_sessions()
    if sessions:
        current = st.session_state.get("sid")
        idx = sessions.index(current) if current in sessions else 0
        picked = st.selectbox("Resume session", sessions, index=idx)
        if picked != current:
            st.session_state["sid"] = picked

    with st.form("new_session"):
        st.subheader("New session")
        target = st.number_input("Target coverage %", 1.0, 100.0, float(DEFAULTS["target_pct"]), 1.0)
        plateau_iters = st.number_input("Plateau window (iterations)", 1, 10, int(DEFAULTS["plateau_iters"]))
        plateau_delta = st.number_input("Plateau min gain %", 0.0, 50.0, float(DEFAULTS["plateau_delta"]), 0.5)
        max_iters = st.number_input("Max iterations", 1, 50, int(DEFAULTS["max_iters"]))
        if st.form_submit_button("Start new session", type="primary"):
            with st.spinner("Generating first test..."):
                st_ = svc.start(
                    target_pct=target, plateau_iters=plateau_iters, plateau_delta=plateau_delta, max_iters=max_iters
                )
            st.session_state["sid"] = st_["session_id"]
            st.rerun()

sid = st.session_state.get("sid")
st.title("Coverage-guided verification: adder4")
if not sid:
    st.info("Start a new session from the sidebar.")
    st.stop()

status = svc.status(sid)
settings = status["settings"]
st.caption(f"Session `{sid}` - MCP clients can drive this same session with session_id=\"{sid}\".")

loop_tab, mut_tab, sum_tab = st.tabs(["Coverage loop", "Mutation testing", "Summary"])

with loop_tab:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Iteration", status["iteration"])
    cov = status["coverage_pct"]
    hist = [h["coverage_pct"] for h in status["history"] if h.get("coverage_pct") is not None]
    delta = f"{hist[-1] - hist[-2]:+.2f}" if len(hist) > 1 else None
    c2.metric("Coverage", f"{cov:.2f}%" if cov is not None else "-", delta)
    c3.metric("Target", f"{settings['target_pct']:.1f}%")
    c4.metric("State", "done" if status["done"] else "awaiting results")

    if cov is not None:
        st.progress(min(cov / 100.0, 1.0))

    if status["done"]:
        st.success(f"Loop finished: {status['stop_reason']}. Head to Mutation testing.")

    pending = status["pending"]
    if pending:
        if pending.get("parse_error"):
            st.error(pending["parse_error"])
        st.subheader(f"Iteration {pending['iteration']}: {pending['focus']}")
        st.caption(f"generator: {pending['generator']}")
        with st.expander("How to run this on EDA Playground", expanded=status["iteration"] == 1):
            st.markdown(pending["instructions"])
            st.markdown("**run.do**")
            st.code(pending["run_do"], language="tcl")
        left, right = st.columns(2)
        with left:
            st.markdown("**testbench.sv** (left pane)")
            st.code(pending["testbench"], language="verilog", line_numbers=True)
        with right:
            st.markdown("**design.sv** (right pane)")
            st.code(pending["design"], language="verilog", line_numbers=True)

        report = st.text_area(
            "Paste the full Riviera-PRO log (coverage report + pass/fail output)",
            height=220,
            key=f"report_{sid}_{pending['iteration']}",
        )
        if st.button("Submit results", type="primary", disabled=not report.strip()):
            with st.spinner("Parsing results and planning next test..."):
                svc.submit_report(sid, report)
            st.rerun()

    if hist:
        st.subheader("Cumulative coverage by iteration")
        df = pd.DataFrame(
            {"coverage %": [h["coverage_pct"] for h in status["history"]]},
            index=pd.Index([h["iteration"] for h in status["history"]], name="iteration"),
        )
        st.line_chart(df, y="coverage %", height=260)

    if status["point_pct"] or status["history"]:
        st.subheader("Last run")
        a, b = st.columns(2)
        with a:
            if status["point_pct"]:
                pts = pd.DataFrame(
                    sorted(status["point_pct"].items()), columns=["coverpoint", "coverage %"]
                ).set_index("coverpoint")
                st.dataframe(pts, width="stretch")
            uncovered = [k for k, v in status["bins"].items() if not v]
            if uncovered:
                st.markdown("**Uncovered bins:** " + ", ".join(f"`{u}`" for u in uncovered))
        with b:
            verdict = {True: "PASSED", False: "FAILED", None: "no verdict"}[status["passed"]]
            st.markdown(f"**Simulation:** {verdict}")
            if status["check_failures"]:
                st.markdown("**Reference-model mismatches**")
                st.code("\n".join(status["check_failures"][:10]))
            if status["assertion_failures"]:
                st.markdown("**Assertion failures**")
                st.code("\n".join(status["assertion_failures"][:10]))
            if status["critique"]:
                st.info(status["critique"])
            if status["next_focus"] and not status["done"]:
                st.markdown(f"**Critic -> next test:** {status['next_focus']}")

with mut_tab:
    data = svc.mutants(sid)
    score = svc.mutation_score(sid)
    if not data["testbench"]:
        st.info("No test suite yet. Run at least one coverage iteration first.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Caught", f"{score['caught']} / {score['total']}")
        m2.metric("Survived", score["survived"])
        m3.metric("Invalid runs", score["invalid"])
        m4.metric("Not run yet", score["total"] - score["run"])
        if not status["done"]:
            st.warning("Coverage loop still running. Suite will grow; results recorded now go stale when it does.")
        st.markdown(
            "Run the **same suite testbench** below against each mutant's design.sv on EDA Playground and paste the log. "
            "A mutant is *caught* when the run reports TEST FAILED, a CHECK_FAIL or an ASSERT_FAIL."
        )
        with st.expander("Suite testbench.sv (same for all 10 mutants)"):
            st.code(data["testbench"], language="verilog", line_numbers=True)
        for m in data["mutants"]:
            r = score["results"].get(m["id"])
            tag = "not run" if r is None else r["verdict"] + (" (stale)" if r["stale"] else "")
            with st.expander(f"{m['id']}  [{m['category']}]  {m['description']}  -  {tag}"):
                st.code(m["design"], language="verilog")
                txt = st.text_area("Paste log", key=f"mut_{sid}_{m['id']}", height=140)
                if st.button("Submit", key=f"mut_btn_{sid}_{m['id']}", disabled=not txt.strip()):
                    res = svc.submit_mutation(sid, m["id"], txt)
                    st.toast(f"{m['id']}: {res['verdict']}")
                    st.rerun()

with sum_tab:
    summ = svc.summary(sid)
    s1, s2, s3 = st.columns(3)
    s1.metric("Coverage achieved", f"{summ['coverage_pct']:.2f}%" if summ["coverage_pct"] is not None else "-")
    s2.metric("Iterations taken", summ["iterations"])
    mut = summ["mutation"]
    s3.metric("Mutation score", f"{mut['caught']} / {mut['total']}", f"{mut['run']} run")
    st.markdown(f"**Stop reason:** {summ['stop_reason'] or 'loop still running'}")
    if status["history"]:
        st.dataframe(
            pd.DataFrame(status["history"])[["iteration", "focus", "coverage_pct", "passed", "parse_source"]],
            width="stretch",
            hide_index=True,
        )
    if mut["results"]:
        st.dataframe(
            pd.DataFrame(
                [{"mutant": k, **v} for k, v in sorted(mut["results"].items())]
            ),
            width="stretch",
            hide_index=True,
        )
