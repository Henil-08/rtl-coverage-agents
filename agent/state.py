from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class IterationRecord(TypedDict, total=False):
    iteration: int
    focus: str
    coverage_pct: float | None
    passed: bool | None
    assertion_failures: list[str]
    check_failures: list[str]
    parse_source: str


class VerifState(TypedDict, total=False):
    target_pct: float
    plateau_iters: int
    plateau_delta: float
    max_iters: int

    iteration: int
    blocks: list[dict]
    testbench: str
    focus: str
    raw_report: str
    regenerate: bool  # last tb didn't compile, redo same iteration
    compile_feedback: str
    parse_error: str

    coverage_pct: float | None
    point_pct: dict[str, float]
    bins: dict[str, bool]
    assertion_failures: list[str]
    check_failures: list[str]
    passed: bool | None
    parse_source: str

    history: Annotated[list[IterationRecord], operator.add]
    critique: str
    next_focus: str
    done: bool
    stop_reason: str
    generator: str


DEFAULTS: dict[str, Any] = {
    "target_pct": 95.0,
    "plateau_iters": 2,
    "plateau_delta": 1.0,
    "max_iters": 10,
}
