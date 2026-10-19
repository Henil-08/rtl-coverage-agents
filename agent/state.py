from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

MODES = ("auto", "approval", "manual")


class VerifState(TypedDict, total=False):
    design: str
    language: str
    mode: str
    target_pct: float
    toggle_target: float
    plateau_iters: int
    plateau_delta: float
    max_iters: int

    use_kb: bool
    model: str
    agent_models: dict
    tb_source: str
    gen_tb: dict
    kb_hits: list[dict]
    plan: list[dict]
    assertions: list[dict]
    blocks: list[dict]
    iteration: int
    testbench: str
    generator: str
    attempts: int

    run_root: str
    run_dir: str
    sim_runs: int
    result: dict
    issue: str
    issue_detail: str
    triage_note: str

    analysis: str
    next_focus: str
    feedback: str
    review: dict
    done: bool
    stop_reason: str

    covered: list[str]
    llm_model: str
    runs: Annotated[list[dict], operator.add]
    history: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]


DEFAULTS: dict[str, Any] = {
    "mode": "auto",
    "target_pct": 100.0,
    "toggle_target": 90.0,
    "plateau_iters": 2,
    "plateau_delta": 1.0,
    "max_iters": 8,
    "use_kb": True,
    "tb_source": "handwritten",
}
