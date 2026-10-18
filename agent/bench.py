"""Agent vs random stimulus at equal simulation effort.

    uv run python -m agent.bench --design dpram --seeds 5
    uv run python -m agent.bench --design adder4 --llm
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import tempfile
from pathlib import Path

from agent.llm import get_llm
from agent.mutation import run_mutants
from agent.service import VerificationService
from agent.sim import simulate
from designs import DESIGNS, get_design
from designs.base import split_assertions

OUT = Path(__file__).resolve().parent.parent / "bench"


def agent_curve(design: str, work: Path, llm=None, language: str = "sv", **settings) -> tuple[list[dict], str]:
    svc = VerificationService(llm=llm, db_path=work / "agent.sqlite", runs_dir=work / "agent_runs")
    st = svc.start(design, "auto", thread_id="bench", language=language, **settings)
    points = []
    for e, h in zip([e for e in st["events"] if e["agent"] == "coverage_analyst"], st["history"]):
        points.append({"iteration": h["iteration"], "functional_pct": h["functional_pct"],
                       "toggle_pct": h.get("toggle_pct")})
    counts = _stimulus_counts(work / "agent_runs" / "bench")
    for p, c in zip(points, counts):
        p["stimulus"] = c
    return points, svc.suite("bench")


def _stimulus_counts(run_root: Path) -> list[int]:
    """Stimulus count of the last clean run of each iteration, read back from the run folders."""
    from agent.sim import collect

    best: dict[int, int] = {}
    for d in sorted(run_root.glob("run_*_iter*")):
        res = collect(d)
        if res.built and res.passed is not None and res.stimulus_count is not None:
            best[int(d.name.split("iter")[1])] = res.stimulus_count
    return [best[k] for k in sorted(best)]


def random_curve(design: str, seed: int, per_iter: int, iters: int, work: Path,
                 language: str = "sv") -> tuple[list[dict], str]:
    d = get_design(design)
    rng = random.Random(seed)
    blocks, points, tb = [], [], ""
    for it in range(1, iters + 1):
        blocks.append({"iteration": it, "focus": f"random seed {seed}", "stimulus": d.random_stimulus(rng, per_iter)})
        tb = d.build_testbench(blocks, [], language)
        r = simulate(work / f"rand_{seed}_{it:02d}", d.sources(), tb, d.dut_hier, language == "uvm")
        points.append({"iteration": it, "stimulus": r.stimulus_count, "functional_pct": r.functional_pct,
                       "toggle_pct": r.code["toggle"]["pct"]})
        if r.functional_pct == 100.0 and (r.code["toggle"]["pct"] or 0) >= 100.0:
            break
    return points, tb


def first_reaching(points: list[dict], key: str, target: float) -> int | None:
    return next((p["stimulus"] for p in points if (p.get(key) or 0) >= target), None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default="dpram", choices=sorted(DESIGNS))
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--per-iter", type=int, default=16, help="random vectors or cycles added per iteration")
    ap.add_argument("--iters", type=int, default=20, help="max random iterations")
    ap.add_argument("--llm", action="store_true", help="use the Groq LLM for the agent run")
    ap.add_argument("--mutants", action="store_true", help="also score each final suite with mutation testing")
    ap.add_argument("--lang", default="sv", choices=["sv", "uvm"], help="testbench language")
    args = ap.parse_args()

    d = get_design(args.design)
    assertions = split_assertions(d.default_assertions)
    OUT.mkdir(exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        agent_pts, agent_tb = agent_curve(args.design, work, get_llm() if args.llm else None, args.lang)
        label = "agent+llm" if args.llm else "agent"
        rows += [{"run": label, **p} for p in agent_pts]
        summary = {label: (first_reaching(agent_pts, "functional_pct", 100.0),
                           first_reaching(agent_pts, "toggle_pct", 90.0), agent_tb)}
        for seed in range(args.seeds):
            pts, tb = random_curve(args.design, seed, args.per_iter, args.iters, work, args.lang)
            rows += [{"run": f"random_{seed}", **p} for p in pts]
            summary[f"random_{seed}"] = (first_reaching(pts, "functional_pct", 100.0),
                                         first_reaching(pts, "toggle_pct", 90.0), tb)

        scores = {}
        if args.mutants:
            for name, (_, _, tb) in summary.items():
                suite = tb.replace("  // no assertions", "\n".join("  " + a["code"] for a in assertions))
                rep = run_mutants(d, suite, work / f"mut_{name}", uvm=args.lang == "uvm")
                scores[name] = f"{rep.get('caught', '?')}/{rep.get('total', '?')}" if rep["golden_ok"] else "suite broke"

    csv_path = OUT / f"{args.design}_{'llm' if args.llm else 'fallback'}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "iteration", "stimulus", "functional_pct", "toggle_pct"])
        w.writeheader()
        w.writerows(rows)

    unit = "vectors" if args.design == "adder4" else "cycles"
    print(f"\n{d.title}: {unit} needed to reach 100% functional / 90% toggle coverage")
    print(f"{'run':<12} {'functional':>11} {'toggle':>8} {'mutants':>8}")
    for name, (fn, tg, _) in summary.items():
        print(f"{name:<12} {str(fn or 'never'):>11} {str(tg or 'never'):>8} {scores.get(name, '-'):>8}")
    rand_fn = [s[0] for k, s in summary.items() if k.startswith("random") and s[0]]
    if rand_fn:
        print(f"random median to 100% functional: {statistics.median(rand_fn)} {unit} "
              f"({len(rand_fn)}/{args.seeds} seeds got there)")
    print(f"curves written to {csv_path}")


if __name__ == "__main__":
    main()
