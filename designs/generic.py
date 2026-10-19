"""Stimulus generators for testbenches the agents wrote, built from the driver tasks' own signatures."""

from __future__ import annotations

import random
import re

_TASK = re.compile(r"\btask\s+(?:automatic\s+)?(\w+)\s*\(([^)]*)\)", re.S)
_ARG = re.compile(r"(?:input\s+)?(?:logic|bit|reg|wire)?\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(\w+)\s*$")


def driver_tasks(testbench: str) -> list[dict]:
    """Driver tasks of a testbench: name and argument widths. Generated stim_itN tasks are skipped."""
    out = []
    for name, args in _TASK.findall(testbench):
        if name.startswith("stim_it") or name in ("body", "run_phase"):
            continue
        parsed = []
        for raw in [a.strip() for a in args.split(",") if a.strip()]:
            m = _ARG.search(raw)
            if not m:
                parsed = None
                break
            hi, lo, arg = m.groups()
            parsed.append({"name": arg, "width": abs(int(hi) - int(lo)) + 1 if hi else 1})
        if parsed is not None and not any(t["name"] == name for t in out):
            out.append({"name": name, "args": parsed})
    return out


def call(task: dict, rng: random.Random) -> str:
    args = ", ".join(f"{a['width']}'d{rng.randrange(2 ** min(a['width'], 64))}" for a in task["args"])
    return f"{task['name']}({args});"


def random_stimulus_for(tasks: list[dict]):
    def gen(rng: random.Random, n: int) -> str:
        return "\n".join(call(rng.choice(tasks), rng) for _ in range(n)) if tasks else ""
    return gen


def fallback_for(tasks: list[dict]):
    """No-LLM fallback for generated testbenches: a seeded burst of random driver calls."""
    def gen(iteration: int, bins: dict, blocks: list[dict], code: dict | None = None) -> tuple[str, str]:
        rng = random.Random(1000 + iteration)
        return f"random burst {iteration}", random_stimulus_for(tasks)(rng, 32)
    return gen
