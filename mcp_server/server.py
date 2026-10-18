from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from agent.llm import get_llm  # noqa: E402
from agent.service import VerificationService  # noqa: E402
from designs import get_design  # noqa: E402
from designs.base import split_assertions  # noqa: E402

mcp = MCPServer(
    "rtl-coverage-agent",
    instructions=(
        "Coverage-guided verification of small SystemVerilog designs on Verilator. "
        "Either let the built-in agents run a session (start_session, then respond while it is paused), "
        "or act as the test writer yourself: read describe_design, then call simulate with your own stimulus "
        "and assertions and read back functional, toggle, branch and expression coverage. "
        "run_mutation_testing scores a session's suite against injected bugs."
    ),
)

_svc: VerificationService | None = None


def svc() -> VerificationService:
    global _svc
    if _svc is None:
        _svc = VerificationService(llm=get_llm())
    return _svc


def _result_view(res: dict) -> dict:
    code = res.get("code") or {}
    return {
        "built": res.get("built"),
        "passed": res.get("passed"),
        "compile_errors": res.get("compile_errors", [])[:10],
        "check_failures": res.get("check_failures", [])[:10],
        "assertion_failures": res.get("assertion_failures", []),
        "functional_pct": res.get("functional_pct"),
        "point_pct": res.get("point_pct", {}),
        "uncovered_bins": [k for k, v in res.get("bins", {}).items() if v == 0],
        "code_coverage": {k: c.get("pct") for k, c in code.items()},
        "missed_code_points": {k: c.get("missed", [])[:20] for k, c in code.items() if c.get("missed")},
    }


def _view(status: dict) -> dict:
    return {
        "session_id": status["session_id"],
        "design": status["design"],
        "mode": status["mode"],
        "language": status["language"],
        "iteration": status["iteration"],
        "done": status["done"],
        "stop_reason": status["stop_reason"],
        "waiting_for": status["pending"],
        "result": _result_view(status["result"]),
        "analysis": status["analysis"],
        "assertions": [{k: a.get(k) for k in ("label", "status", "reason", "code")} for a in status["assertions"]],
        "history": status["history"],
        "recent_events": status["events"][-12:],
    }


@mcp.tool()
def list_designs() -> list[dict]:
    """Designs available for verification."""
    return svc().designs()


@mcp.tool()
def describe_design(design: str) -> dict:
    """Spec, RTL, the fixed covergroup, and how to write stimulus and assertions for `simulate`."""
    d = get_design(design)
    return {
        "spec": d.spec(),
        "rtl": d.sources(),
        "covergroup": d.covergroup(),
        "how_to_drive": d.harness_doc,
        "assertion_signals": d.signals,
        "assertion_form": "<label>: assert property (@(posedge clk) <property>);",
        "mutants": [{"id": m.id, "category": m.category, "description": m.description} for m in d.mutants],
    }


@mcp.tool()
def start_session(
    design: str,
    mode: str = "auto",
    language: str = "sv",
    target_pct: float | None = None,
    toggle_target: float | None = None,
    max_iters: int | None = None,
) -> dict:
    """Start the agent loop. mode: auto (runs to the end), approval (pauses at every review gate),
    manual (pauses so a person runs the generated run.sh). language: sv (plain SystemVerilog testbench)
    or uvm (UVM testbench, slower to build). Returns where it stopped or paused."""
    return _view(svc().start(design, mode, language=language, target_pct=target_pct,
                             toggle_target=toggle_target, max_iters=max_iters))


@mcp.tool()
def get_session(session_id: str) -> dict:
    """Current state of a session, including what it is waiting for."""
    return _view(svc().status(session_id))


@mcp.tool()
def respond(session_id: str, action: str = "approve", feedback: str = "") -> dict:
    """Answer a paused session. action: approve, reject (redo the step using feedback), or stop
    (results step only). In manual mode, call it with approve after running the command."""
    return _view(svc().respond(session_id, action, feedback))


@mcp.tool()
def simulate(design: str, stimulus: str, assertions: str = "", language: str = "sv") -> dict:
    """Run your own stimulus (a task body using the design's driver tasks) and optional assertions
    inside the design's fixed testbench on Verilator. language: sv or uvm. Returns pass/fail and coverage."""
    d = get_design(design)
    tb = d.build_testbench([{"iteration": 1, "focus": "mcp", "stimulus": stimulus}], split_assertions(assertions),
                           language)
    return _result_view(svc().simulate(design, tb, language=language))


@mcp.tool()
def run_mutation_testing(session_id: str) -> dict:
    """Run the session's suite on the golden design and every mutant. Reports which mutants were caught
    and whether assertions or the reference model caught them."""
    return svc().run_mutation(session_id)


if __name__ == "__main__":
    mcp.run("stdio")
