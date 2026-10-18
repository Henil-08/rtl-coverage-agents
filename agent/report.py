"""Full written record of a session, for the Report tab and for download."""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


def _pct(v) -> str:
    return f"{v:.2f}%" if isinstance(v, (int, float)) else "-"


def _when(t: float | None) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else "-"


def llm_usage(events: list[dict]) -> dict:
    kinds = Counter(e["kind"] for e in events if e["agent"] in (
        "planner", "assertion_writer", "stimulus_writer", "coverage_analyst", "triage"))
    return {"llm": kinds.get("llm", 0), "fallback": kinds.get("fallback", 0), "rule": kinds.get("rule", 0)}


def markdown(status: dict, design, mutation: dict | None) -> str:
    res = status["result"]
    code = res.get("code") or {}
    events = status["events"]
    usage = llm_usage(events)
    start = events[0]["t"] if events and "t" in events[0] else None
    end = events[-1]["t"] if events and "t" in events[-1] else None
    out = [f"# Verification report: {design.title}", ""]

    out += ["## Summary", "", "| Field | Value |", "|---|---|",
            f"| Session | `{status['session_id']}` |",
            f"| Design | `{design.name}` ({', '.join(design.rtl_files)}) |",
            f"| Mode | {status['mode']} |",
            f"| Testbench | {'UVM' if status.get('language') == 'uvm' else 'SystemVerilog'} |",
            f"| LLM | {status.get('llm_model') or '-'} |",
            f"| Started / finished | {_when(start)} / {_when(end)} |",
            f"| Iterations | {len(status['history'])} |",
            f"| Simulations | {len(status.get('runs', []))} |",
            f"| Agent steps by LLM / fallback / rule | {usage['llm']} / {usage['fallback']} / {usage['rule']} |",
            f"| Outcome | {status['stop_reason'] or 'not finished'} |",
            ""]
    s = status["settings"]
    out += [f"Stop rule: functional ≥ {s['target_pct']}% and toggle ≥ {s['toggle_target']}%, "
            f"at most {s['max_iters']} iterations, plateau = {s['plateau_iters']} rounds under "
            f"{s['plateau_delta']} points of gain.", ""]

    bins = res.get("bins", {})
    out += ["## Final coverage", "", "| Metric | Hit | Total | Coverage |", "|---|---|---|---|",
            f"| Functional (bins) | {sum(v > 0 for v in bins.values())} | {len(bins)} | {_pct(res.get('functional_pct'))} |"]
    for kind in ("toggle", "branch", "expr", "line"):
        c = code.get(kind) or {}
        if c.get("total"):
            out.append(f"| {kind} | {c['hit']} | {c['total']} | {_pct(c.get('pct'))} |")
    out += ["", "| Coverpoint | Coverage |", "|---|---|"]
    out += [f"| `{cp}` | {_pct(p)} |" for cp, p in sorted(res.get("point_pct", {}).items())]
    out.append("")

    out += ["## Iterations", ""]
    blocks = {b["iteration"]: b for b in status["blocks"]}
    runs_by_it: dict[int, list[dict]] = {}
    for r in status.get("runs", []):
        runs_by_it.setdefault(r["iteration"], []).append(r)
    for h in status["history"]:
        it = h["iteration"]
        b = blocks.get(it, {})
        out += [f"### Iteration {it}: {h.get('focus', '')}", "",
                f"- Stimulus by: {b.get('source', h.get('generator', '-'))}",
                f"- Functional {_pct(h.get('functional_pct'))}, toggle {_pct(h.get('toggle_pct'))}, "
                f"branch {_pct(h.get('branch_pct'))}, expression {_pct(h.get('expr_pct'))}",
                f"- Newly covered bins: {', '.join(f'`{x}`' for x in h.get('newly_covered', [])) or 'none'}"]
        for r in runs_by_it.get(it, []):
            verdict = "build failed" if not r["built"] else ("PASS" if r["passed"] else "FAIL")
            out.append(f"- Run {r['n']} ({r['by']}, {r.get('seconds', 0)}s): {verdict}, "
                       f"{len(r.get('failures', []))} failures, `{r['run_dir']}`")
            for e in r.get("compile_errors", [])[:3]:
                out.append(f"  - `{e}`")
        notes = [e for e in events if e["iteration"] == it and e["agent"] in ("triage", "coverage_analyst")]
        for e in notes:
            out.append(f"- {e['agent']}: {e['summary']}")
        out += ["", "```systemverilog", b.get("stimulus", "").strip(), "```", ""]

    out += ["## Assertions", "", "| Label | Status | Repairs | Note |", "|---|---|---|---|"]
    for a in status["assertions"]:
        out.append(f"| `{a['label']}` | {a['status']} | {a.get('repairs', 0)} | {a.get('reason', '')} |")
    out += [""] + [f"- `{a['code']}`" for a in status["assertions"]] + [""]

    fails = [(r, f) for r in status.get("runs", []) for f in r.get("failures", [])]
    out += ["## Failures seen during the session", ""]
    if fails:
        out += ["| Run | Iteration | Time (ps) | Kind | Detail |", "|---|---|---|---|---|"]
        out += [f"| {r['n']} | {r['iteration']} | {f['time']} | {f['kind']} | {f['label']}: {f['text']} |"
                for r, f in fails[:100]]
    else:
        out.append("None.")
    out.append("")

    missing = [k for k, v in bins.items() if v == 0]
    out += ["## Remaining gaps", "", f"Uncovered bins: {', '.join(f'`{m}`' for m in missing) or 'none'}", ""]
    for kind in ("branch", "expr", "toggle"):
        missed = (code.get(kind) or {}).get("missed", [])
        if missed:
            out += [f"Missed {kind} points ({len(missed)}):", ""] + [f"- `{m}`" for m in missed[:40]] + [""]

    out += ["## Mutation testing", ""]
    if not mutation:
        out.append("Not run.")
    elif not mutation.get("golden_ok"):
        out.append(f"Suite failed on the unmodified design: {mutation.get('golden_errors')}")
    else:
        out += [f"Caught {mutation['caught']}/{mutation['total']} "
                f"({mutation['caught_by_assertions']} by assertions)"
                + (" — stale, the suite changed afterwards." if mutation.get("stale") else "."), "",
                "| Mutant | Fault | Description | Verdict | By assertion | By reference model |",
                "|---|---|---|---|---|---|"]
        out += [f"| {r['id']} | {r['category']} | {r['description']} | {r['verdict']} | "
                f"{'yes' if r['by_assertion'] else ''} | {'yes' if r['by_scoreboard'] else ''} |"
                for r in mutation["results"]]
    out.append("")

    out += ["## Agent trace", ""]
    out += [f"- it {e['iteration']} · {e['agent']} · {e['kind']}: {e['summary']}" for e in events]
    return "\n".join(out) + "\n"


def bundle(status: dict, design, mutation: dict | None, testbench: str) -> bytes:
    """Zip with the report, the session as JSON, the final testbench, the RTL and every waveform."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.md", markdown(status, design, mutation))
        z.writestr("session.json", json.dumps({**status, "mutation": mutation}, indent=1, default=str))
        if testbench:
            z.writestr("testbench.sv", testbench)
        for name, text in design.sources().items():
            z.writestr(f"rtl/{name}", text)
        for r in status.get("runs", []):
            if r.get("wave") and Path(r["wave"]).exists():
                z.write(r["wave"], f"waves/run_{r['n']:03d}_iter{r['iteration']:02d}.vcd")
        for r in (mutation or {}).get("results", []):
            if r.get("wave") and Path(r["wave"]).exists():
                z.write(r["wave"], f"waves/mutant_{r['id']}.vcd")
    return buf.getvalue()
