from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.nodes import make_nodes
from agent.state import VerifState

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sessions.sqlite"
RUNS_DIR = ROOT / "runs"


def _rejected(state: VerifState) -> bool:
    return state.get("review", {}).get("action") == "reject"


def _after_plan(state: VerifState) -> str:
    return "planner" if _rejected(state) else "assertion_writer"


def _after_assertions(state: VerifState) -> str:
    if _rejected(state):
        return "assertion_writer"
    return "simulator" if state.get("blocks") else "stimulus_writer"


def _after_testbench(state: VerifState) -> str:
    return "stimulus_writer" if _rejected(state) else "simulator"


def _after_triage(state: VerifState) -> str:
    issue = state.get("issue", "")
    if issue == "missing_output":
        return "simulator"
    if issue == "stimulus_compile":
        return "stimulus_writer"
    if issue in ("assertion_compile", "assertion_false_positive"):
        return "assertion_writer"
    return "coverage_analyst"


def _after_results(state: VerifState) -> str:
    if state.get("done"):
        return END
    return "stimulus_writer"


def build_graph(llm=None, checkpointer=None, runs_dir: Path = RUNS_DIR):
    g = StateGraph(VerifState)
    for name, fn in make_nodes(llm, runs_dir).items():
        g.add_node(name, fn)
    g.add_edge(START, "planner")
    g.add_edge("planner", "review_plan")
    g.add_conditional_edges("review_plan", _after_plan, ["planner", "assertion_writer"])
    g.add_edge("assertion_writer", "review_assertions")
    g.add_conditional_edges("review_assertions", _after_assertions,
                            ["assertion_writer", "simulator", "stimulus_writer"])
    g.add_edge("stimulus_writer", "review_testbench")
    g.add_conditional_edges("review_testbench", _after_testbench, ["stimulus_writer", "simulator"])
    g.add_edge("simulator", "triage")
    g.add_conditional_edges("triage", _after_triage,
                            ["simulator", "stimulus_writer", "assertion_writer", "coverage_analyst"])
    g.add_edge("coverage_analyst", "review_results")
    g.add_conditional_edges("review_results", _after_results, ["stimulus_writer", END])
    return g.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: Path = DB_PATH) -> SqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
