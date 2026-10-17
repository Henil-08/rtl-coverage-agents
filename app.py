from __future__ import annotations

import os
import re
import uuid

import pandas as pd
import streamlit as st

import ui
from agent.llm import DEFAULT_MODEL, get_llm
from agent.service import VerificationService
from agent.state import DEFAULTS
from designs import DESIGNS, get_design

st.set_page_config(page_title="RTL coverage agents", page_icon="◈", layout="wide")
ui.inject_css()

MODES = {
    "auto": ("Auto", "The agents run every step, Verilator included, and stop on their own."),
    "approval": ("Approval", "The agents pause for your OK on the plan, the assertions, every testbench and "
                             "every result. Reject with feedback and that agent redoes the step."),
    "manual": ("Manual", "The agents write each test; you run the generated run.sh in a terminal and tell "
                         "them when it is done."),
}
BLURB = {
    "dpram": "Two ports, one clock, read-first, port A wins write collisions. Collisions and "
             "read-after-write across ports make coverage hard to hit by chance.",
    "adder4": "Small combinational warm-up. Only 512 possible inputs, so it is a sanity check rather "
              "than a real challenge.",
}
HELP = {
    "target": "Stop once this share of the functional coverage bins is hit "
              "(averaged per coverpoint, the way commercial simulators report it).",
    "toggle": "Also require this share of the design's signal bits to have toggled both 0→1 and 1→0. "
              "Set 0 to ignore toggle coverage.",
    "max": "Hard cap on test-writing rounds, whatever the coverage.",
    "window": "How many recent rounds to look at when deciding the agents are stuck.",
    "delta": "If neither functional nor toggle coverage rose by at least this many points in each of "
             "those rounds, stop: more rounds are unlikely to help.",
}


@st.cache_resource
def get_service(model: str) -> VerificationService:
    return VerificationService(llm=get_llm(model))


ss = st.session_state

with st.sidebar:
    st.markdown("### ◈ RTL coverage agents")
    if st.button("New session", type="primary", width="stretch", icon=":material/add:"):
        ss.pop("sid", None)
        st.rerun()
    with st.expander("LLM"):
        model = st.text_input("Groq model", os.getenv("GROQ_MODEL", DEFAULT_MODEL))
        llm_on = get_llm(model) is not None
        st.caption("Connected" if llm_on else "No GROQ_API_KEY: agents use deterministic fallbacks.")
    svc = get_service(model)
    sessions = svc.list_sessions()
    if sessions:
        st.markdown("**Sessions**")
        current = ss.get("sid")
        picked = st.radio("Sessions", sessions, label_visibility="collapsed",
                          index=sessions.index(current) if current in sessions else None)
        if picked and picked != current:
            ss["sid"] = picked
            st.rerun()


def run_live(call, events: list[dict], issue: str = "") -> None:
    """Run a service call and stream agent events into the main page while it works."""
    st.markdown("#### Agents at work")
    pipe, feed = st.empty(), st.empty()
    pipe.html(ui.pipeline_html(events, running=True, issue=issue))
    live = list(events)

    def on_event(e: dict) -> None:
        live.append(e)
        pipe.html(ui.pipeline_html(live, running=True))
        feed.html(ui.feed_html(live, limit=10))

    call(on_event)
    st.rerun()


def setup_view() -> None:
    ui.hero("New verification session",
            "Pick a design, how much control you want, and when the agents should stop.",
            [ui.chip("LLM on" if llm_on else "fallback only", "accent" if llm_on else "warn")])

    design = st.segmented_control("Design", list(DESIGNS), default="dpram", format_func=lambda n: DESIGNS[n].title)
    design = design or "dpram"
    d = DESIGNS[design]
    coverpoints = len(re.findall(r"^\s*(?:c[px]_\w+)\s*:", d.covergroup(), re.M))
    st.html(f'<div class="design-card"><h4>{d.title}</h4><p>{BLURB.get(design, "")}</p>'
            f'<div class="chips" style="margin-top:.7rem">{ui.chip(f"{coverpoints} coverpoints")}'
            f'{ui.chip(f"{len(d.mutants)} mutants")}{ui.chip(", ".join(d.rtl_files))}</div></div>')

    st.space("small")
    mode = st.segmented_control("Mode", list(MODES), default="auto", format_func=lambda m: MODES[m][0]) or "auto"
    st.caption(MODES[mode][1])

    st.space("small")
    st.markdown("**When to stop**")
    c1, c2, c3 = st.columns(3)
    target = c1.number_input("Functional target %", 1.0, 100.0, float(DEFAULTS["target_pct"]), 1.0, help=HELP["target"])
    toggle = c2.number_input("Toggle target %", 0.0, 100.0, float(DEFAULTS["toggle_target"]), 1.0, help=HELP["toggle"])
    max_iters = c3.number_input("Max iterations", 1, 30, int(DEFAULTS["max_iters"]), help=HELP["max"])
    c4, c5, _ = st.columns(3)
    window = c4.number_input("Plateau window", 1, 10, int(DEFAULTS["plateau_iters"]), help=HELP["window"])
    delta = c5.number_input("Plateau min gain (points)", 0.0, 50.0, float(DEFAULTS["plateau_delta"]), 0.5,
                            help=HELP["delta"])
    st.caption(f"The loop ends at the first of: functional ≥ {target:.0f}% and toggle ≥ {toggle:.0f}%; "
               f"{max_iters} iterations; or {window} rounds in a row where neither coverage rose by {delta:g} "
               f"point{'' if delta == 1 else 's'}. "
               "A reference-model mismatch also stops it, since that may be a real design bug.")

    st.space("small")
    if st.button("Start session", type="primary", icon=":material/play_arrow:"):
        sid = f"{design}-{uuid.uuid4().hex[:6]}"
        ss["sid"] = sid
        ss["launch"] = ("start", dict(design=design, mode=mode, thread_id=sid, target_pct=target,
                                      toggle_target=toggle, max_iters=max_iters, plateau_iters=window,
                                      plateau_delta=delta))
        st.rerun()


def gate_panel(sid: str, pending: dict) -> None:
    step = pending["step"]
    with st.container(key="gate"):
        if step == "run_simulation":
            st.markdown(f"#### Your turn: run iteration {pending['iteration']}")
            st.markdown("Run this in a terminal. Verilator writes the logs and `coverage.dat` into the run "
                        "folder, and the agents read them from there.")
            st.code(pending["command"], language="bash")
            with st.expander("testbench.sv"):
                st.code(pending["testbench"], language="verilog", line_numbers=True)
            if st.button("I ran it", type="primary"):
                ss["launch"] = ("respond", "approve", "")
                st.rerun()
            return

        titles = {"plan": "Review the verification plan", "assertions": "Review the assertions",
                  "testbench": f"Review the testbench for iteration {pending['iteration']}",
                  "results": f"Review the results of iteration {pending['iteration']}"}
        st.markdown(f"#### {titles[step]}")
        if step == "plan":
            st.dataframe(pd.DataFrame(pending["plan"]), hide_index=True, width="stretch")
        elif step == "assertions":
            st.code("\n".join(a["code"] for a in pending["assertions"]), language="verilog")
        elif step == "testbench":
            st.markdown(f"**Focus:** {pending['focus']}")
            st.markdown("New stimulus for this iteration:")
            st.code(pending.get("stimulus", ""), language="verilog", line_numbers=True, height=320)
            with st.expander("Full testbench.sv"):
                st.code(pending["testbench"], language="verilog", line_numbers=True)
        else:
            r = pending["result"]
            st.markdown(f"**{'PASS' if r.get('passed') else 'FAIL'}** · functional {r.get('functional_pct')}%")
            st.markdown(pending["analysis"])
            if pending["done"]:
                st.info(f"The analyst wants to stop: {pending['stop_reason']}")
        feedback = st.text_area("Feedback", placeholder="Why you reject, or guidance for the next test",
                                key=f"fb_{sid}_{step}_{pending['iteration']}")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Approve", type="primary", width="stretch"):
            ss["launch"] = ("respond", "approve", feedback)
            st.rerun()
        if step == "results":
            if b2.button("Stop here", width="stretch"):
                ss["launch"] = ("respond", "stop", "")
                st.rerun()
        elif b2.button("Reject and redo", width="stretch"):
            ss["launch"] = ("respond", "reject", feedback)
            st.rerun()


def live_view(sid: str, launch: tuple) -> None:
    if launch[0] == "start":
        ui.hero("Starting session", sid, [])
        run_live(lambda cb: svc.start(on_event=cb, **launch[1]), [])
    else:
        status = svc.status(sid)
        ui.hero(get_design(status["design"]).title, sid, [])
        run_live(lambda cb: svc.respond(sid, launch[1], launch[2], on_event=cb), status["events"], status["issue"])


def session_view(sid: str) -> None:
    status = svc.status(sid) if svc.exists(sid) else None
    if status is None or status["design"] not in DESIGNS:
        st.warning("This session cannot be opened. It may have been made by an older version of the app.")
        return

    d = get_design(status["design"])
    res, code = status["result"], status["result"].get("code") or {}
    mut = svc.mutation_report(sid)
    if status["done"]:
        state = ui.chip("design bug?", "bad") if status["issue"] == "design_mismatch" else ui.chip("done", "good")
    elif status["pending"]:
        state = ui.chip("waiting for you", "accent")
    else:
        state = ui.chip("stopped")
    ui.hero(d.title, status["stop_reason"] or "In progress",
            [ui.chip(sid), ui.chip(f"{status['mode']} mode"), state])

    st.html(ui.pipeline_html(status["events"], issue=status["issue"]))

    def pct(kind: str) -> float | None:
        return (code.get(kind) or {}).get("pct")

    def fmt(v: float | None) -> str:
        return f"{v:.1f}%" if v is not None else "–"

    fn = res.get("functional_pct")
    bins = res.get("bins", {})
    hit = sum(v > 0 for v in bins.values())
    active = sum(a["status"] == "active" for a in status["assertions"])
    tog = code.get("toggle") or {}
    st.html(ui.kpis_html([
        ("Iteration", str(status["iteration"]), None, f"{sum(e['agent'] == 'simulator' for e in status['events'])} simulations"),
        ("Functional", fmt(fn), fn, f"{hit}/{len(bins)} bins" if bins else "not run yet"),
        ("Toggle", fmt(pct("toggle")), pct("toggle"), f"{tog.get('hit', 0)}/{tog.get('total', 0)} bit transitions"),
        ("Branch", fmt(pct("branch")), pct("branch"), "if/else arms in the RTL"),
        ("Expression", fmt(pct("expr")), pct("expr"), "input combinations per expression"),
        ("Mutants caught", f"{mut['caught']}/{mut['total']}" if mut and mut.get("golden_ok") else "–",
         100.0 * mut["caught"] / mut["total"] if mut and mut.get("golden_ok") else None,
         f"{active} assertions active" if not mut else
         f"{mut['caught_by_assertions']} by assertions" + (" · stale" if mut.get("stale") else "")),
    ]))

    if status["pending"]:
        gate_panel(sid, status["pending"])
    if status["done"] and status["issue"] == "design_mismatch" and status["triage_note"]:
        st.error(f"Triage: {status['triage_note']}")

    progress, plan_tab, cov_tab, tb_tab, mut_tab = st.tabs(
        ["Progress", "Plan & assertions", "Coverage", "Testbench", "Mutation testing"])

    with progress:
        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown("**Coverage per iteration**")
            if status["history"]:
                hist = pd.DataFrame(status["history"]).set_index("iteration")
                chart = hist[["functional_pct", "toggle_pct"]].rename(
                    columns={"functional_pct": "functional %", "toggle_pct": "toggle %"})
                st.line_chart(chart, height=300, y_label="coverage %", x_label="iteration")
            else:
                st.html('<div class="empty">No finished iteration yet.</div>')
        with right:
            st.markdown("**Agent timeline**")
            with st.container(height=360, border=False):
                st.html(ui.feed_html(status["events"]))

    with plan_tab:
        st.dataframe(pd.DataFrame(status["plan"]), hide_index=True, width="stretch")
        for a in status["assertions"]:
            tone = "good" if a["status"] == "active" else "bad"
            st.html(f'<div class="chips">{ui.chip(a["label"])}{ui.chip(a["status"], tone)}'
                    f'{ui.chip(a["reason"][:90]) if a.get("reason") else ""}</div>')
            st.code(a["code"], language="verilog")

    with cov_tab:
        if not bins:
            st.html('<div class="empty">No simulation yet.</div>')
        else:
            left, right = st.columns(2, gap="large")
            with left:
                st.markdown("**Functional coverage by coverpoint**")
                pts = pd.DataFrame(sorted(res["point_pct"].items()), columns=["coverpoint", "coverage"])
                st.dataframe(pts, hide_index=True, width="stretch", column_config={
                    "coverage": st.column_config.ProgressColumn("coverage", min_value=0, max_value=100, format="%.0f%%")})
                missing = [k for k, v in bins.items() if v == 0]
                st.markdown("**Uncovered bins**")
                st.html('<div class="chips">' + ("".join(ui.chip(m, "warn") for m in missing)
                                                 or ui.chip("none", "good")) + "</div>")
            with right:
                st.markdown("**Code coverage on the design**")
                rows = [{"kind": k, "hit": v["hit"], "total": v["total"], "coverage": v.get("pct") or 0}
                        for k, v in code.items() if v["total"]]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
                    "coverage": st.column_config.ProgressColumn("coverage", min_value=0, max_value=100, format="%.0f%%")})
                for kind in ("branch", "expr", "toggle"):
                    missed = (code.get(kind) or {}).get("missed", [])
                    if missed:
                        with st.expander(f"Missed {kind} points ({len(missed)})"):
                            st.code("\n".join(missed))

    with tb_tab:
        if status["testbench"]:
            st.code(status["testbench"], language="verilog", line_numbers=True, height=520)
        for name, text in d.sources().items():
            with st.expander(name):
                st.code(text, language="verilog", line_numbers=True)
        if res.get("log"):
            with st.expander("Last simulator log"):
                st.code(res["log"])

    with mut_tab:
        st.markdown(f"Ten bugs are injected into `{d.rtl_files[0]}` one at a time, and the current suite runs against "
                    "each. A failing run means the bug was caught. The table says whether the assertions or the "
                    "testbench's reference model noticed it.")
        if st.button("Run mutation testing", disabled=not status["blocks"], icon=":material/bug_report:"):
            with st.spinner("Building and running every mutant..."):
                svc.run_mutation(sid)
            st.rerun()
        if mut:
            if not mut["golden_ok"]:
                st.error(f"The suite fails on the unmodified design: {mut['golden_errors']}")
            else:
                if mut["stale"]:
                    st.warning("The suite changed since this run. Run it again for a current score.")
                st.dataframe(pd.DataFrame(mut["results"])[
                    ["id", "category", "description", "verdict", "by_assertion", "by_scoreboard"]],
                    hide_index=True, width="stretch")


# Two top-level slots. While agents run, the page slot is sent as an empty element, which drops
# every element of the previous page at once instead of leaving it faded under the live view.
live_slot, page_slot = st.empty(), st.empty()
launch = ss.pop("launch", None)
if launch and ss.get("sid"):
    with live_slot.container():
        live_view(ss["sid"], launch)
else:
    with page_slot.container():
        if ss.get("sid"):
            session_view(ss["sid"])
        else:
            setup_view()
