"""Testbench architect: writes a self-checking testbench from the spec and the RTL's real ports,
then has to pass a series of gates before any test is built on top of it."""

from __future__ import annotations

import json
import random
import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from agent import events, prompts, rtl
from agent.mutation import run_mutants
from agent.sim import simulate
from designs import get_design
from designs.base import Design, strip_fences
from designs.generic import call, driver_tasks, fallback_for, random_stimulus_for

MAX_SV_TRIES = 4
MAX_UVM_TRIES = 3
SMOKE_CALLS = 300
MARKERS = {"sv": ("// @ASSERTIONS", "// @STIMULUS_TASKS", "// @STIMULUS_CALLS"),
           "uvm": ("// @ASSERTIONS", "// @SEQUENCES", "// @SEQUENCE_CALLS")}


def design_for(state: dict) -> Design:
    """The design as the agents should see it: with the generated testbench if the session has one."""
    d = get_design(state["design"])
    gen = state.get("gen_tb")
    if not gen or not gen.get("ok"):
        return d
    tasks = gen["drivers"]
    return replace(
        d,
        drivers=tuple(t["name"] for t in tasks),
        harness_doc=gen["harness_doc"],
        signals=gen["signals"],
        wave_signals=tuple(gen["wave_signals"]) or d.wave_signals,
        fallback=fallback_for(tasks),
        random_stimulus=random_stimulus_for(tasks),
        templates={k: gen[k] for k in ("sv", "uvm") if gen.get(k)},
    )


def _tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text or "", re.S)
    return strip_fences(m.group(1)) if m else ""


def _ports_text(info: dict) -> str:
    return "\n".join(f"- {p['dir']} {'[' + str(p['width'] - 1) + ':0] ' if p['width'] > 1 else ''}{p['name']}"
                     for p in info["ports"])


def structure_problems(tb: str, lang: str, top: str, tasks: list[dict] | None = None) -> list[str]:
    probs = [f"missing the marker line `{m}`" for m in MARKERS[lang] if m not in tb]
    if not re.search(r"\bmodule\s+tb\b", tb):
        probs.append("the top module must be called tb")
    if not re.search(rf"\b{re.escape(top)}\b(\s*#\s*\(.*?\))?\s+dut\b", tb, re.S):
        probs.append(f"the DUT must be instantiated as `{top} ... dut (...)`")
    for needed in ("CHECK_FAIL", "TEST PASSED", "TEST FAILED", "$dumpfile", "$dumpvars"):
        if needed not in tb:
            probs.append(f"missing `{needed}`")
    if lang == "uvm":
        if "class base_seq" not in tb:
            probs.append("missing class base_seq")
        for t in tasks or []:
            if not re.search(rf"\btask\s+(automatic\s+)?{t['name']}\s*\(", tb):
                probs.append(f"base_seq must have a task `{t['name']}` like the SV driver")
        if not re.search(r"\benv\b", tb) or "sqr" not in tb:
            probs.append("the test needs a member env with env.agent.sqr")
    return probs


def architect(design: Design, plan: list[dict], language: str, ask: Callable[..., str | None], workdir: Path,
              feedback: str = "") -> dict:
    """Write and validate a testbench. Returns {"ok": True, "sv": ..., "uvm": ..., ...} or {"ok": False, ...}."""
    info = rtl.ports(design.sources(), design.extra.get("top"))
    top, gates = info["top"], []

    def gate(name: str, ok: bool, detail: str = "") -> None:
        gates.append({"gate": name, "ok": ok, "detail": detail})
        events.emit("tb_gate", gate=name, ok=ok, detail=detail)

    base = prompts.TB_USER.format(
        spec=design.spec(), rtl="\n\n".join(f"// {n}\n{t}" for n, t in design.sources().items()), top=top,
        ports=_ports_text(info), clock=info["clock"] or "none (combinational)", reset=info["reset"] or "none",
        plan=json.dumps(plan, indent=1), feedback=f"\nReviewer feedback: {feedback}\n" if feedback else "")
    failed: tuple[str, str, str] | None = None
    retried = set()
    sv = tasks = None
    how = waves = ""
    for attempt in range(MAX_SV_TRIES):
        prompt = base if failed is None else base + "\n\n" + prompts.TB_REPAIR.format(
            gate=failed[0], detail=failed[1][:3000], testbench=failed[2])
        text = ask(prompts.TB_SYSTEM, prompt, "testbench_architect")
        if not text:
            return {"ok": False, "reason": "the LLM did not answer", "gates": gates}
        tb, how, waves, rtl_bug = (_tag(text, "testbench"), _tag(text, "how_to_drive"), _tag(text, "wave_signals"),
                                   _tag(text, "rtl_bug"))
        tasks = driver_tasks(tb)
        probs = structure_problems(tb, "sv", top) + ([] if tasks else ["no driver task with plain logic arguments"])
        if probs:
            gate("structure", False, "; ".join(probs))
            failed = ("structure", "\n".join(probs), tb)
            continue
        gate("structure", True, f"{len(tasks)} driver tasks: {', '.join(t['name'] for t in tasks)}")

        rng = random.Random(0)
        stim = "\n".join(call(rng.choice(tasks), rng) for _ in range(SMOKE_CALLS))
        draft = replace(design, templates={"sv": tb})
        r = simulate(workdir / f"sv_try{attempt + 1}", design.sources(),
                     draft.build_testbench([{"iteration": 1, "focus": "smoke", "stimulus": stim}], [], "sv"),
                     design.dut_hier)
        if not r.built:
            gate("compile", False, "\n".join(r.compile_errors[:8]))
            failed = ("compile", "\n".join(r.compile_errors[:15]), tb)
            continue
        gate("compile", True)
        if r.passed is not True:
            detail = "\n".join(r.check_failures[:10]) or r.log[-1500:]
            if rtl_bug:
                gate("golden_run", False, f"architect says the RTL breaks the spec: {rtl_bug}")
                return {"ok": False, "design_bug": rtl_bug, "mismatches": r.check_failures[:20], "gates": gates,
                        "sv": tb}
            gate("golden_run", False, detail)
            failed = ("golden run: the reference model disagrees with the RTL on random stimulus", detail, tb)
            continue
        gate("golden_run", True, f"{r.stimulus_count or SMOKE_CALLS} random transactions, no mismatches")

        dead = [cp for cp, pct in r.point_pct.items() if pct == 0]
        if dead and "reach" not in retried:
            retried.add("reach")
            gate("coverage_reachable", False, f"never hit by random stimulus: {', '.join(dead)}")
            failed = ("coverage reachability", f"these coverpoints got no hits from {SMOKE_CALLS} random "
                      f"transactions; their bins are probably unreachable or wrongly written: {dead}", tb)
            continue
        gate("coverage_reachable", not dead, f"{len(r.point_pct) - len(dead)}/{len(r.point_pct)} coverpoints "
             f"hit by random stimulus" + (f"; still unhit: {', '.join(dead)}" if dead else ""))

        suite = draft.build_testbench([{"iteration": 1, "focus": "smoke", "stimulus": stim}], [], "sv")
        mut = run_mutants(draft, suite, workdir / f"mutants_try{attempt + 1}") if design.mutants else None
        caught = (mut or {}).get("caught", 0)
        if mut and caught == 0 and "mutants" not in retried:
            retried.add("mutants")
            gate("mutant_smoke", False, f"0/{len(design.mutants)} planted bugs caught by random stimulus")
            failed = ("checker strength", "random stimulus through your testbench caught none of these planted "
                      "bugs, so the reference model or its comparisons are too weak:\n"
                      + "\n".join(m.description for m in design.mutants), tb)
            continue
        if mut:
            gate("mutant_smoke", caught > 0, f"{caught}/{mut.get('total', 0)} planted bugs caught by random stimulus")
        sv = tb
        break

    if sv is None:
        return {"ok": False, "reason": f"the testbench still failed `{failed[0] if failed else '?'}` after "
                f"{MAX_SV_TRIES} attempts", "gates": gates, "sv": failed[2] if failed else ""}

    ports_line = ", ".join(p["name"] for p in info["ports"])
    out = {
        "ok": True,
        "sv": sv,
        "drivers": tasks,
        "harness_doc": how or "Driver tasks: " + ", ".join(f"{t['name']}(...)" for t in tasks),
        "signals": f"DUT ports at tb level: {ports_line}. Reference-model predictions: exp_<output>. "
                   f"Clock: clk; inputs change on the falling edge.",
        "wave_signals": [w if w.startswith("tb.") else f"tb.{w}" for w in re.split(r"[,\s]+", waves) if w],
        "gates": gates,
        "top": top,
    }
    if language != "uvm":
        return out

    failed = None
    for attempt in range(MAX_UVM_TRIES):
        fb = "" if failed is None else (f"\nYOUR PREVIOUS UVM TESTBENCH FAILED: {failed[0]}\n{failed[1][:3000]}\n"
                                        f"Previous version:\n{failed[2]}\nFix it.")
        text = ask(prompts.TB_SYSTEM, prompts.UVM_USER.format(spec=design.spec(), top=top, ports=_ports_text(info),
                                                              sv_testbench=sv, feedback=fb), "testbench_architect")
        ub = _tag(text, "testbench") or strip_fences(text or "")
        probs = structure_problems(ub, "uvm", top, tasks)
        if probs:
            gate("uvm_structure", False, "; ".join(probs))
            failed = ("structure", "\n".join(probs), ub)
            continue
        gate("uvm_structure", True)
        draft = replace(design, templates={"uvm": ub})
        r = simulate(workdir / f"uvm_try{attempt + 1}", design.sources(),
                     draft.build_testbench([{"iteration": 1, "focus": "smoke", "stimulus": stim}], [], "uvm"),
                     design.dut_hier, uvm=True)
        if not r.built:
            gate("uvm_compile", False, "\n".join(r.compile_errors[:8]))
            failed = ("compile", "\n".join(r.compile_errors[:15]), ub)
            continue
        gate("uvm_compile", True)
        if r.passed is not True:
            detail = "\n".join(r.check_failures[:10]) or r.log[-1500:]
            gate("uvm_golden_run", False, detail)
            failed = ("golden run", detail, ub)
            continue
        gate("uvm_golden_run", True)
        sv_hits = {k for k, v in simulate(workdir / "sv_ref", design.sources(), replace(
            design, templates={"sv": sv}).build_testbench([{"iteration": 1, "stimulus": stim}], [], "sv"),
            design.dut_hier).bins.items() if v}
        uvm_hits = {k for k, v in r.bins.items() if v}
        gate("uvm_matches_sv", uvm_hits == sv_hits,
             "same bins hit as the SV testbench" if uvm_hits == sv_hits else
             f"bins differ: only SV {sorted(sv_hits - uvm_hits)[:6]}, only UVM {sorted(uvm_hits - sv_hits)[:6]}")
        out["uvm"] = ub
        return out
    gate("uvm", False, f"UVM testbench still failing after {MAX_UVM_TRIES} attempts; continuing in SystemVerilog")
    out["uvm_failed"] = True
    return out
