from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.nodes import make_nodes
from agent.state import VerifState

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sessions.sqlite"


def _after_parse(state: VerifState) -> str:
    if state.get("parse_error"):
        return "await_human_input"
    if state.get("regenerate"):
        return "generate_test"
    return "critique_and_loop"


def _after_critique(state: VerifState) -> str:
    return END if state.get("done") else "generate_test"


def build_graph(llm=None, checkpointer=None):
    nodes = make_nodes(llm)
    g = StateGraph(VerifState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "generate_test")
    g.add_edge("generate_test", "await_human_input")
    g.add_edge("await_human_input", "parse_results")
    g.add_conditional_edges("parse_results", _after_parse, ["await_human_input", "generate_test", "critique_and_loop"])
    g.add_conditional_edges("critique_and_loop", _after_critique, ["generate_test", END])
    return g.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: Path = DB_PATH) -> SqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
