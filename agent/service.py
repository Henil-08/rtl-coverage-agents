"""Session API used by both the Streamlit app and the MCP server."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from agent.graph import DB_PATH, build_graph, sqlite_checkpointer
from agent.parser import parse_report
from agent.state import DEFAULTS
from agent.tb_template import EDA_INSTRUCTIONS, RUN_DO, build_testbench, dut_source
from mutation.mutants import MUTANTS, MUTANTS_BY_ID, verdict


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class VerificationService:
    def __init__(self, llm=None, db_path: Path = DB_PATH):
        self.saver = sqlite_checkpointer(db_path)
        self.graph = build_graph(llm, self.saver)
        self._conn = self.saver.conn
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS mutation_results (
                       thread_id TEXT, mutant_id TEXT, verdict TEXT, suite_hash TEXT,
                       raw TEXT, ts REAL, PRIMARY KEY (thread_id, mutant_id))"""
            )
            self._conn.commit()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def start(self, thread_id: str | None = None, **settings: Any) -> dict:
        thread_id = thread_id or uuid.uuid4().hex[:8]
        if self.exists(thread_id):
            return self.status(thread_id)
        init = {**DEFAULTS, **{k: v for k, v in settings.items() if k in DEFAULTS and v is not None}}
        init.update({"iteration": 0, "blocks": [], "history": []})
        self.graph.invoke(init, self._config(thread_id))
        return self.status(thread_id)

    def exists(self, thread_id: str) -> bool:
        return bool(self.graph.get_state(self._config(thread_id)).values)

    def status(self, thread_id: str) -> dict:
        snap = self.graph.get_state(self._config(thread_id))
        values = snap.values or {}
        pending = None
        interrupts = getattr(snap, "interrupts", None) or [i for t in snap.tasks for i in t.interrupts]
        if interrupts:
            pending = interrupts[0].value
        history = values.get("history", [])
        return {
            "session_id": thread_id,
            "exists": bool(values),
            "iteration": values.get("iteration", 0),
            "done": bool(values.get("done")),
            "stop_reason": values.get("stop_reason", ""),
            "coverage_pct": values.get("coverage_pct"),
            "point_pct": values.get("point_pct", {}),
            "bins": values.get("bins", {}),
            "assertion_failures": values.get("assertion_failures", []),
            "check_failures": values.get("check_failures", []),
            "passed": values.get("passed"),
            "critique": values.get("critique", ""),
            "next_focus": values.get("next_focus", ""),
            "history": history,
            "pending": pending,
            "settings": {k: values.get(k, v) for k, v in DEFAULTS.items()},
        }

    def submit_report(self, thread_id: str, report: str) -> dict:
        st = self.status(thread_id)
        if not st["pending"]:
            raise ValueError(f"session {thread_id} is not waiting for a coverage report")
        self.graph.invoke(Command(resume=report), self._config(thread_id))
        return self.status(thread_id)

    def list_sessions(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT thread_id, MAX(rowid) FROM checkpoints GROUP BY thread_id ORDER BY MAX(rowid) DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def suite_testbench(self, thread_id: str) -> str | None:
        values = self.graph.get_state(self._config(thread_id)).values or {}
        blocks = values.get("blocks") or []
        if not blocks:
            return None
        # rebuild so assertions dropped after the last tb was generated stay out
        return build_testbench(values.get("iteration", len(blocks)), blocks)

    def mutants(self, thread_id: str) -> dict:
        tb = self.suite_testbench(thread_id)
        return {
            "session_id": thread_id,
            "testbench": tb,
            "run_do": RUN_DO,
            "instructions": EDA_INSTRUCTIONS.replace("design.sv", "the mutant's design.sv"),
            "mutants": [
                {"id": m.id, "category": m.category, "description": m.description, "design": m.source()}
                for m in MUTANTS
            ],
        }

    def submit_mutation(self, thread_id: str, mutant_id: str, report: str) -> dict:
        if mutant_id not in MUTANTS_BY_ID:
            raise ValueError(f"unknown mutant {mutant_id}; expected one of {list(MUTANTS_BY_ID)}")
        tb = self.suite_testbench(thread_id)
        if tb is None:
            raise ValueError(f"session {thread_id} has no test suite yet")
        parsed = parse_report(report)
        v = verdict(parsed)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO mutation_results VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, mutant_id, v, _hash(tb), report, time.time()),
            )
            self._conn.commit()
        return {
            "mutant_id": mutant_id,
            "verdict": v,
            "check_failures": parsed["check_failures"][:5],
            "assertion_failures": parsed["assertion_failures"][:5],
            "score": self.mutation_score(thread_id),
        }

    def mutation_score(self, thread_id: str) -> dict:
        tb = self.suite_testbench(thread_id)
        current = _hash(tb) if tb else None
        with self._lock:
            rows = self._conn.execute(
                "SELECT mutant_id, verdict, suite_hash FROM mutation_results WHERE thread_id = ?", (thread_id,)
            ).fetchall()
        results = {}
        for mid, v, h in rows:
            results[mid] = {"verdict": v, "stale": h != current}
        fresh = {k: r for k, r in results.items() if not r["stale"]}
        caught = sum(r["verdict"] == "caught" for r in fresh.values())
        return {
            "caught": caught,
            "survived": sum(r["verdict"] == "survived" for r in fresh.values()),
            "invalid": sum(r["verdict"] == "invalid" for r in fresh.values()),
            "run": len(fresh),
            "total": len(MUTANTS),
            "score_pct": round(100.0 * caught / len(MUTANTS), 1),
            "results": results,
        }

    def summary(self, thread_id: str) -> dict:
        st = self.status(thread_id)
        return {
            "session_id": thread_id,
            "coverage_pct": st["coverage_pct"],
            "iterations": len(st["history"]),
            "done": st["done"],
            "stop_reason": st["stop_reason"],
            "coverage_history": [h.get("coverage_pct") for h in st["history"]],
            "mutation": self.mutation_score(thread_id),
        }

    @staticmethod
    def design() -> str:
        return dut_source()
