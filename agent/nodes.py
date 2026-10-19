from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from agent import events, prompts
from agent.sim import collect, prepare, run
from agent.state import DEFAULTS, VerifState
from designs import get_design
from designs.base import dedupe_labels, split_assertions, strip_fences, valid_stimulus

MAX_COMPILE_RETRIES = 2
UVM_NOTE = ("\nThis session uses a UVM testbench: your stimulus becomes the body() of a uvm_sequence that "
            "extends base_seq, which provides exactly these tasks. Do not declare classes or use uvm_do macros.")
MAX_REPAIRS = 1


def _cfg(state: VerifState, key: str):
    return state.get(key, DEFAULTS[key])


def _tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.S)
    return strip_fences(m.group(1)) if m else ""


def _uncovered(result: dict | None) -> list[str]:
    return [k for k, v in (result or {}).get("bins", {}).items() if v == 0]


def _code_summary(result: dict | None) -> str:
    code = (result or {}).get("code") or {}
    parts = [f"{k} {v['hit']}/{v['total']}" for k, v in code.items() if v.get("total")]
    return ", ".join(parts) or "not run yet"


def _missed(result: dict | None, limit: int = 15) -> list[str]:
    code = (result or {}).get("code") or {}
    out = []
    for kind in ("branch", "expr", "line", "toggle"):
        out += [f"{kind}: {m}" for m in code.get(kind, {}).get("missed", [])]
    return out[:limit]


def retrieve(design, per_query: int = 2, limit: int = 8) -> list[dict]:
    """Search the knowledge base with the design title and each behaviour and corner case in its spec."""
    from rag.kb import load

    base = load()
    if base is None:
        return []
    bullets = re.findall(r"^\s*-\s+(.+)$", design.spec(), re.M)
    queries = [design.title] + [re.sub(r"[`*]", "", b) for b in bullets][:10]
    seen, hits = set(), []
    for q in queries:
        for h in base.search(q, per_query):
            key = (h["doc"], h["page"], h["text"][:60])
            if key not in seen:
                seen.add(key)
                hits.append(h)
    hits = sorted(hits, key=lambda h: -h["score"])[:limit]
    for i, h in enumerate(hits, 1):
        h["ref"] = f"S{i}"
    return hits


def cite(plan: list[dict], hits: list[dict]) -> list[dict]:
    """Give every plan feature without a citation the best matching passage."""
    from rag.kb import load

    base = load()
    if base is None:
        return hits
    known = {(h["doc"], h["page"], h["text"][:60]): h["ref"] for h in hits}
    for p in plan:
        valid = [r for r in p.get("sources", []) if r in known.values()]
        if valid:
            p["sources"] = valid
            continue
        top = base.search(p["feature"], 1)
        if not top:
            continue
        key = (top[0]["doc"], top[0]["page"], top[0]["text"][:60])
        if key not in known:
            top[0]["ref"] = f"S{len(hits) + 1}"
            hits.append(top[0])
            known[key] = top[0]["ref"]
        p["sources"] = [known[key]]
    return hits


def make_nodes(llm=None, runs_dir: Path | None = None) -> dict[str, Any]:
    runs_dir = runs_dir or Path("runs")
    last_error = {"msg": ""}

    def ask(system: str, user: str, agent: str = "") -> str | None:
        last_error["msg"] = ""
        if llm is None:
            return None
        for attempt in range(3):
            try:
                msgs = [("system", system), ("user", user)]
                if events.active() and hasattr(llm, "stream"):
                    buf, parts = events.TokenBuffer(agent), []
                    events.emit("llm_start", agent=agent)
                    for chunk in llm.stream(msgs):
                        text = getattr(chunk, "content", "") or ""
                        if text:
                            parts.append(text)
                            buf.add(text)
                    buf.flush()
                    events.emit("llm_end", agent=agent)
                    return "".join(parts)
                resp = llm.invoke(msgs)
                return getattr(resp, "content", str(resp))
            except Exception as e:
                last_error["msg"] = f"{type(e).__name__}: {str(e)[:160]}"
                if "RateLimit" not in type(e).__name__ or attempt == 2:
                    return None
                m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(e))
                time.sleep(min(30.0, (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 10.0) + 0.5)
        return None

    def _event(state: VerifState, agent: str, kind: str, summary: str) -> dict:
        if kind == "fallback" and last_error["msg"]:
            summary += f" (LLM error, used fallback: {last_error['msg']})"
        return {"agent": agent, "kind": kind, "summary": summary, "iteration": state.get("iteration", 0),
                "t": round(time.time(), 2)}

    def planner(state: VerifState) -> dict:
        d = get_design(state["design"])
        feedback = state.get("feedback", "")
        hits = retrieve(d) if _cfg(state, "use_kb") else []
        refs = ""
        if hits:
            refs = "\nREFERENCE MATERIAL (excerpts from public datasheets and user guides)\n" + "\n".join(
                f"[{h['ref']}] {h['title']}{' p.' + str(h['page']) if h['page'] else ''}: {h['text'][:700]}"
                for h in hits) + "\n"
        user = prompts.PLANNER_USER.format(spec=d.spec(), covergroup=d.covergroup(), references=refs)
        if feedback:
            user += f"\nReviewer feedback on your last plan: {feedback}"
        text = ask(prompts.PLANNER_SYSTEM, user, "planner")
        plan = None
        if text:
            m = re.search(r"\[.*\]", text, re.S)
            try:
                plan = [p for p in json.loads(m.group(0)) if isinstance(p, dict) and p.get("feature")] if m else None
            except json.JSONDecodeError:
                plan = None
        kind = "llm" if plan else "fallback"
        plan = [dict(p) for p in (plan or d.default_plan)]
        if _cfg(state, "use_kb"):
            hits = cite(plan, hits)
        summary = f"{len(plan)} features in the verification plan"
        if hits:
            summary += f", {len(hits)} knowledge-base passages from {len({h['doc'] for h in hits})} documents"
        elif _cfg(state, "use_kb"):
            summary += " (knowledge base not built: uv run python -m rag build)"
        return {
            "plan": plan,
            "kb_hits": hits,
            "feedback": "",
            "events": [_event(state, "planner", kind, summary)],
        }

    def assertion_writer(state: VerifState) -> dict:
        d = get_design(state["design"])
        assertions = [dict(a) for a in state.get("assertions", [])]
        issue = state.get("issue", "")
        events = []

        if issue in ("assertion_false_positive", "assertion_compile"):
            labels = set(state.get("issue_detail", "").split(","))
            for a in assertions:
                if a["label"] not in labels or a["status"] != "active":
                    continue
                problem = (
                    "it fired on the correct design while the reference model saw no mismatch"
                    if issue == "assertion_false_positive"
                    else f"it does not compile: {state.get('triage_note', '')}"
                )
                fixed = None
                if a.get("repairs", 0) < MAX_REPAIRS:
                    text = ask(prompts.ASSERTION_SYSTEM, prompts.ASSERTION_REPAIR_USER.format(
                        spec=d.spec(), signals=d.signals, code=a["code"], problem=problem, label=a["label"]),
                        "assertion_writer")
                    if text and "DROP" not in text:
                        fixed = next(iter(split_assertions(_tag(text, "assertion") or text)), None)
                if fixed:
                    a.update(code=fixed["code"].replace(fixed["label"], a["label"], 1),
                             repairs=a.get("repairs", 0) + 1)
                    events.append(_event(state, "assertion_writer", "llm", f"repaired {a['label']}"))
                else:
                    a.update(status="dropped", reason=problem)
                    events.append(_event(state, "assertion_writer", "fallback", f"dropped {a['label']}: {problem}"))
        else:
            feedback = state.get("feedback", "")
            user = prompts.ASSERTION_USER.format(
                spec=d.spec(), signals=d.signals, plan=json.dumps(state.get("plan", []), indent=1), count="4 to 8")
            if feedback:
                user += f"\nReviewer feedback on your last set: {feedback}"
            text = ask(prompts.ASSERTION_SYSTEM, user, "assertion_writer")
            new = split_assertions(_tag(text, "assertions") or text) if text else []
            kind = "llm" if new else "fallback"
            new = new or split_assertions(d.default_assertions)
            assertions = dedupe_labels(new, [])
            events.append(_event(state, "assertion_writer", kind, f"{len(assertions)} assertions from the spec"))

        out: dict = {"assertions": assertions, "feedback": "", "issue": "", "issue_detail": "", "events": events}
        if state.get("blocks"):
            out["testbench"] = d.build_testbench(state["blocks"], assertions, state.get("language", "sv"))
        return out

    def stimulus_writer(state: VerifState) -> dict:
        d = get_design(state["design"])
        retry = state.get("issue") == "stimulus_compile"
        review = state.get("review") or {}
        redo = retry or (review.get("step") == "testbench" and review.get("action") == "reject")
        it = state.get("iteration", 0) if redo else state.get("iteration", 0) + 1
        attempts = state.get("attempts", 0) + 1 if retry else 0
        blocks = [b for b in state.get("blocks", []) if b["iteration"] != it]
        result = state.get("result") or {}
        bins = result.get("bins", {})

        block, kind = None, "fallback"
        if attempts <= MAX_COMPILE_RETRIES:
            feedback = ""
            if retry:
                feedback += f"YOUR LAST STIMULUS FAILED TO COMPILE. Fix it:\n{state.get('triage_note', '')}\n"
            if state.get("feedback"):
                feedback += f"Reviewer feedback: {state['feedback']}\n"
            fp = result.get("functional_pct")
            text = ask(prompts.STIMULUS_SYSTEM, prompts.STIMULUS_USER.format(
                spec=d.spec(),
                harness=d.harness_doc + (UVM_NOTE if state.get("language") == "uvm" else ""),
                covergroup=d.covergroup(),
                plan=json.dumps(state.get("plan", []), indent=1),
                iteration=it,
                previous=[b.get("focus", "") for b in blocks] or "none",
                coverage=f"{fp:.2f}%" if fp is not None else "not run yet",
                points=result.get("point_pct", {}) or "not run yet",
                uncovered="\n".join(f"- {u}" for u in _uncovered(result)) or "- everything (first run)",
                code=_code_summary(result),
                missed="\n".join(f"- {m}" for m in _missed(result)) or "- none yet",
                guidance=state.get("next_focus") or "start broad: every operation and the corner cases in the spec",
                feedback=feedback,
            ), "stimulus_writer")
            if text:
                stim = _tag(text, "stimulus")
                if valid_stimulus(stim, d.drivers):
                    block = {"iteration": it, "focus": _tag(text, "focus") or "LLM-directed test",
                             "stimulus": stim, "source": "llm"}
                    kind = "llm"
        if block is None:
            focus, stim = d.fallback(it, bins, blocks, result.get("code"))
            block = {"iteration": it, "focus": focus, "stimulus": stim, "source": "fallback"}

        blocks.append(block)
        return {
            "iteration": it,
            "attempts": attempts,
            "blocks": blocks,
            "testbench": d.build_testbench(blocks, state.get("assertions", []), state.get("language", "sv")),
            "generator": kind,
            "issue": "",
            "issue_detail": "",
            "feedback": "",
            "review": {},
            "events": [{**_event(state, "stimulus_writer", kind, block["focus"]), "iteration": it}],
        }

    def simulator(state: VerifState) -> dict:
        d = get_design(state["design"])
        if state.get("issue") == "missing_output" and state.get("run_dir"):
            run_dir = Path(state["run_dir"])
        else:
            n = state.get("sim_runs", 0) + 1
            run_dir = Path(state.get("run_root", str(runs_dir))) / f"run_{n:03d}_iter{state['iteration']:02d}"
        prepare(run_dir, d.sources(), state["testbench"], uvm=state.get("language") == "uvm")
        if _cfg(state, "mode") == "manual":
            interrupt({
                "step": "run_simulation",
                "iteration": state["iteration"],
                "run_dir": str(run_dir.resolve()),
                "command": f"bash {(run_dir / 'run.sh').resolve()}",
                "testbench": state["testbench"],
            })
            res = collect(run_dir, d.dut_hier)
            kind = "human"
        else:
            res = run(run_dir, d.dut_hier)
            kind = "tool"
        result = res.to_dict()
        result["log"] = result["log"][-6000:]
        if not res.built and not res.compile_errors and kind == "human":
            summary = "no simulation output found in the run directory"
        elif not res.built:
            summary = f"build failed: {res.compile_errors[0] if res.compile_errors else 'unknown error'}"
        else:
            summary = (f"{'PASS' if res.passed else 'FAIL'}, functional {res.functional_pct}%, "
                       f"{_code_summary(result)}")
        record = {
            "n": state.get("sim_runs", 0) + 1,
            "iteration": state["iteration"],
            "run_dir": str(run_dir),
            "by": kind,
            "built": res.built,
            "passed": res.passed,
            "functional_pct": res.functional_pct,
            "compile_errors": res.compile_errors[:5],
            "failures": res.failures[:50],
            "wave": res.wave,
            "seconds": res.seconds,
            "assertions": [a["label"] for a in state.get("assertions", []) if a["status"] == "active"],
        }
        return {"run_dir": str(run_dir), "result": result, "sim_runs": record["n"], "runs": [record],
                "events": [_event(state, "simulator", kind, summary)]}

    def triage(state: VerifState) -> dict:
        d = get_design(state["design"])
        res = state.get("result") or {}
        assertions = state.get("assertions", [])
        labels = {a["label"] for a in assertions if a["status"] == "active"}

        if not res.get("built"):
            errors = res.get("compile_errors") or []
            if not errors:
                return {"issue": "missing_output", "issue_detail": "", "triage_note": "",
                        "events": [_event(state, "triage", "rule", "no results yet, run the simulation again")]}
            tb_lines = state.get("testbench", "").splitlines()
            bad = set()
            for e in errors:
                m = re.search(r"testbench\.sv:(\d+)", e)
                if m and int(m.group(1)) <= len(tb_lines):
                    line = tb_lines[int(m.group(1)) - 1]
                    bad |= {lbl for lbl in labels if re.match(rf"\s*{re.escape(lbl)}\s*:", line)}
            note = "\n".join(errors[:8])
            if bad:
                return {"issue": "assertion_compile", "issue_detail": ",".join(sorted(bad)), "triage_note": note,
                        "events": [_event(state, "triage", "rule", f"assertion compile error in {sorted(bad)}")]}
            if state.get("attempts", 0) > MAX_COMPILE_RETRIES:
                return {"issue": "build_broken", "issue_detail": "", "triage_note": note,
                        "events": [_event(state, "triage", "rule", "build still failing after retries, stopping")]}
            return {"issue": "stimulus_compile", "issue_detail": "", "triage_note": note,
                    "events": [_event(state, "triage", "rule", "stimulus compile error, sending back to the writer")]}

        checks, fired = res.get("check_failures", []), res.get("assertion_failures", [])
        if fired and not checks:
            fp = sorted(set(fired) & labels)
            return {"issue": "assertion_false_positive", "issue_detail": ",".join(fp), "triage_note": "",
                    "events": [_event(state, "triage", "rule",
                                      f"{fp} fired on the golden design with a clean reference model: assertion bug")]}
        if checks:
            note = ask(prompts.TRIAGE_SYSTEM, prompts.TRIAGE_USER.format(
                spec=d.spec(), checks=checks[:10], asserts=fired,
                codes=[a["code"] for a in assertions if a["label"] in fired]), "triage") or ""
            return {"issue": "design_mismatch", "issue_detail": "", "triage_note": note,
                    "events": [_event(state, "triage", "llm" if note else "rule",
                                      f"reference model mismatch ({len(checks)}): possible design bug")]}
        return {"issue": "", "issue_detail": "", "triage_note": "",
                "events": [_event(state, "triage", "rule", "clean run")]}

    def coverage_analyst(state: VerifState) -> dict:
        res = state.get("result") or {}
        pct = res.get("functional_pct") or 0.0
        it = state.get("iteration", 0)
        record = {
            "iteration": it,
            "focus": next((b["focus"] for b in state.get("blocks", []) if b["iteration"] == it), ""),
            "generator": state.get("generator", ""),
            "functional_pct": pct,
            "bins_hit": sum(v > 0 for v in res.get("bins", {}).values()),
            "bins_total": len(res.get("bins", {})),
            **{f"{k}_pct": v.get("pct") for k, v in (res.get("code") or {}).items()},
            "passed": res.get("passed"),
            "assertions_active": sum(a["status"] == "active" for a in state.get("assertions", [])),
            "run_dir": state.get("run_dir", ""),
        }
        covered_before = set(state.get("covered", []))
        hit_now = {k for k, v in res.get("bins", {}).items() if v > 0}
        record["newly_covered"] = sorted(hit_now - covered_before)
        toggle = record.get("toggle_pct") or 0.0
        history = [h["functional_pct"] for h in state.get("history", [])] + [pct]
        toggles = [h.get("toggle_pct") or 0.0 for h in state.get("history", [])] + [toggle]
        n, delta = _cfg(state, "plateau_iters"), _cfg(state, "plateau_delta")

        def gain(series: list[float], i: int) -> float:
            return series[-i] - series[-i - 1]

        done, reason = False, ""
        if state.get("issue") == "design_mismatch":
            done, reason = True, "reference model mismatch: possible design bug, see triage"
        elif state.get("issue") == "build_broken":
            done, reason = True, "testbench does not build, see the last run log"
        elif pct >= _cfg(state, "target_pct") and toggle >= _cfg(state, "toggle_target"):
            done, reason = True, (f"targets reached: functional {pct:.2f}% (>= {_cfg(state, 'target_pct'):.0f}), "
                                  f"toggle {toggle:.2f}% (>= {_cfg(state, 'toggle_target'):.0f})")
        elif it >= _cfg(state, "max_iters"):
            done, reason = True, f"max iterations ({it}) reached at {pct:.2f}%"
        elif len(history) > n and all(max(gain(history, i), gain(toggles, i)) < delta for i in range(1, n + 1)):
            done, reason = True, f"plateau at {pct:.2f}% functional, {toggle:.2f}% toggle (gain < {delta}% for {n} iterations)"

        uncovered = _uncovered(res)
        if uncovered:
            guidance = "close: " + ", ".join(uncovered[:8])
        else:
            guidance = f"functional coverage complete; raise toggle coverage ({toggle:.1f}%)"
        kind = "rule"
        if not done:
            text = ask(prompts.ANALYST_SYSTEM, prompts.ANALYST_USER.format(
                plan=json.dumps(state.get("plan", []), indent=1), iteration=it, focus=record["focus"],
                history=history, points=res.get("point_pct", {}), uncovered=uncovered or "none",
                code=_code_summary(res), missed=_missed(res)), "coverage_analyst")
            if text:
                guidance, kind = text.strip(), "llm"
        return {
            "covered": sorted(hit_now | covered_before),
            "done": done,
            "stop_reason": reason,
            "next_focus": guidance,
            "analysis": guidance,
            "history": [record],
            "events": [_event(state, "coverage_analyst", kind, reason or guidance[:160])],
        }

    def gate(step: str):
        def node(state: VerifState) -> dict:
            if _cfg(state, "mode") != "approval":
                return {"review": {"step": step, "action": "approve", "feedback": ""}}
            payload = {"step": step, "iteration": state.get("iteration", 0)}
            if step == "plan":
                payload["plan"] = state.get("plan", [])
            elif step == "assertions":
                payload["assertions"] = state.get("assertions", [])
            elif step == "testbench":
                block = next((b for b in state.get("blocks", []) if b["iteration"] == state.get("iteration")), {})
                payload.update(testbench=state.get("testbench", ""), focus=block.get("focus", ""),
                               stimulus=block.get("stimulus", ""))
            else:
                res = dict(state.get("result") or {})
                res.pop("log", None)
                payload.update(result=res, analysis=state.get("analysis", ""),
                               done=state.get("done", False), stop_reason=state.get("stop_reason", ""))
            answer = interrupt(payload)
            if isinstance(answer, str):
                answer = {"action": "approve" if not answer.strip() else "reject", "feedback": answer}
            action = answer.get("action", "approve")
            feedback = answer.get("feedback", "") or ""
            out = {"review": {"step": step, "action": action, "feedback": feedback},
                   "events": [_event(state, f"review_{step}", "human", f"{action}{': ' + feedback if feedback else ''}")]}
            if feedback:
                out["feedback"] = feedback
            if step == "results" and action == "stop":
                out.update(done=True, stop_reason="stopped by reviewer")
            return out

        return node

    nodes = {
        "planner": planner,
        "review_plan": gate("plan"),
        "assertion_writer": assertion_writer,
        "review_assertions": gate("assertions"),
        "stimulus_writer": stimulus_writer,
        "review_testbench": gate("testbench"),
        "simulator": simulator,
        "triage": triage,
        "coverage_analyst": coverage_analyst,
        "review_results": gate("results"),
    }
    return {name: _published(name, fn) for name, fn in nodes.items()}


def _published(name: str, fn):
    """Publish when a node starts and everything it produced when it finishes."""
    def node(state: VerifState) -> dict:
        events.emit("node_start", node=name, iteration=state.get("iteration", 0))
        out = fn(state)
        update = {k: v for k, v in out.items() if k != "events"}
        if isinstance(update.get("result"), dict):
            update["result"] = {k: v for k, v in update["result"].items() if k != "log"}
        events.emit("node_done", node=name, update=update, events=out.get("events", []))
        return out

    return node
