from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent import events
from agent.sim import simulate
from designs.base import Design


def run_mutants(design: Design, testbench: str, out_dir: Path, workers: int = 4, uvm: bool = False) -> dict:
    """Run the suite on the golden design and on every mutant. A mutant is caught when the
    run fails; caught_by says whether assertions, the reference model, or both noticed."""
    events.emit("mutation_start", total=len(design.mutants),
                mutants=[{"id": m.id, "category": m.category, "description": m.description} for m in design.mutants])
    golden = simulate(out_dir / "golden", design.sources(), testbench, design.dut_hier, uvm)
    events.emit("mutation_golden", ok=bool(golden.passed))
    if not golden.passed:
        return {"golden_ok": False, "golden_errors": golden.compile_errors or golden.check_failures
                or golden.assertion_failures, "results": []}

    def one(m):
        r = simulate(out_dir / m.id, design.mutant_sources(m), testbench, design.dut_hier, uvm)
        if not r.built or r.passed is None:
            verdict = "invalid"
        else:
            verdict = "survived" if r.passed else "caught"
        out = {
            "id": m.id,
            "category": m.category,
            "description": m.description,
            "verdict": verdict,
            "by_assertion": bool(r.assertion_failures),
            "by_scoreboard": bool(r.check_failures),
            "assertions": r.assertion_failures,
            "first_check": r.check_failures[0] if r.check_failures else "",
            "failures": r.failures[:20],
            "wave": r.wave,
        }
        events.emit("mutant_result", result={k: v for k, v in out.items() if k != "failures"})
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ctx = contextvars.copy_context()
        results = list(pool.map(lambda m: ctx.copy().run(one, m), design.mutants))
    return {"golden_ok": True, "results": results, **score(results)}


def score(results: list[dict]) -> dict:
    n = len(results)
    caught = sum(r["verdict"] == "caught" for r in results)
    by_assert = sum(r["verdict"] == "caught" and r["by_assertion"] for r in results)
    return {
        "total": n,
        "caught": caught,
        "caught_by_assertions": by_assert,
        "survived": [r["id"] for r in results if r["verdict"] == "survived"],
        "invalid": [r["id"] for r in results if r["verdict"] == "invalid"],
        "score_pct": round(100.0 * caught / n, 1) if n else 0.0,
        "assertion_score_pct": round(100.0 * by_assert / n, 1) if n else 0.0,
    }
