from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from agent.llm import get_llm  # noqa: E402
from agent.service import VerificationService  # noqa: E402

mcp = MCPServer(
    "adder4-coverage-agent",
    instructions=(
        "Human-in-the-loop coverage closure for a 4-bit SystemVerilog adder. "
        "1) propose_test -> run the returned testbench.sv + design.sv on EDA Playground "
        "(Synopsys VCS, Cadence Xcelium or Siemens Questa). 2) submit_coverage_report with the full log; repeat with the next test it "
        "returns until done. 3) list_mutants, run the suite testbench against each mutant, and "
        "submit_mutation_result for each."
    ),
)

_svc: VerificationService | None = None


def svc() -> VerificationService:
    global _svc
    if _svc is None:
        _svc = VerificationService(llm=get_llm())
    return _svc


def _view(status: dict) -> dict:
    out = {
        "session_id": status["session_id"],
        "iteration": status["iteration"],
        "coverage_pct": status["coverage_pct"],
        "done": status["done"],
        "stop_reason": status["stop_reason"],
        "uncovered_bins": [k for k, v in status["bins"].items() if not v],
        "point_pct": status["point_pct"],
        "assertion_failures": status["assertion_failures"][:10],
        "check_failures": status["check_failures"][:10],
        "critique": status["critique"],
        "next_focus": status["next_focus"],
    }
    if status["pending"]:
        out["next_test"] = status["pending"]
    if status["done"]:
        out["summary"] = svc().summary(status["session_id"])
    return out


@mcp.tool()
def propose_test(
    session_id: str | None = None,
    target_pct: float | None = None,
    plateau_iters: int | None = None,
    plateau_delta: float | None = None,
    max_iters: int | None = None,
) -> dict:
    """Start a session, or return the test the session is waiting on.

    next_test has testbench.sv, design.sv and run instructions. Settings only apply to new sessions.
    """
    s = svc()
    if session_id and s.exists(session_id):
        return _view(s.status(session_id))
    return _view(
        s.start(
            session_id,
            target_pct=target_pct,
            plateau_iters=plateau_iters,
            plateau_delta=plateau_delta,
            max_iters=max_iters,
        )
    )


@mcp.tool()
def submit_coverage_report(session_id: str, report: str) -> dict:
    """Submit the full simulator log for the pending test. Returns coverage plus next_test or a summary."""
    return _view(svc().submit_report(session_id, report))


@mcp.tool()
def list_mutants(session_id: str) -> dict:
    """Suite testbench plus the 10 mutant designs to run it against."""
    s = svc()
    data = s.mutants(session_id)
    data["score"] = s.mutation_score(session_id)
    return data


@mcp.tool()
def submit_mutation_result(session_id: str, mutant_id: str, report: str) -> dict:
    """Log from running the suite against one mutant (M01..M10). Returns caught/survived/invalid and the score."""
    return svc().submit_mutation(session_id, mutant_id, report)


if __name__ == "__main__":
    mcp.run("stdio")
