"""Session API shared by the Streamlit app and the MCP server."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from langgraph.types import Command

from agent.graph import DB_PATH, RUNS_DIR, build_graph, sqlite_checkpointer
from agent.mutation import run_mutants
from agent.sim import simulate
from agent.state import DEFAULTS, MODES
from designs import DESIGNS, get_design

RECURSION_LIMIT = 400


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class VerificationService:
    def __init__(self, llm=None, db_path: Path = DB_PATH, runs_dir: Path = RUNS_DIR):
        self.llm_model = getattr(llm, "model_name", None) or ("" if llm is None else type(llm).__name__)
        self.runs_dir = Path(runs_dir)
        self.saver = sqlite_checkpointer(db_path)
        self.graph = build_graph(llm, self.saver, self.runs_dir)
        self._conn = self.saver.conn
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS mutation_runs (
                       thread_id TEXT PRIMARY KEY, suite_hash TEXT, report TEXT, ts REAL)"""
            )
            self._conn.commit()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}

    def _drive(self, payload, thread_id: str, on_event: Callable[[dict], None] | None) -> dict:
        for update in self.graph.stream(payload, self._config(thread_id), stream_mode="updates"):
            if on_event is None:
                continue
            for node, values in update.items():
                if isinstance(values, dict):
                    for ev in values.get("events", []):
                        on_event({"node": node, **ev})
        return self.status(thread_id)

    def start(self, design: str, mode: str = "auto", thread_id: str | None = None,
              on_event: Callable[[dict], None] | None = None, language: str = "sv", **settings: Any) -> dict:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if language not in get_design(design).languages():
            raise ValueError(f"{design} has no {language} testbench; choose from {get_design(design).languages()}")
        thread_id = thread_id or f"{design}-{uuid.uuid4().hex[:6]}"
        if self.exists(thread_id):
            return self.status(thread_id)
        init = dict(DEFAULTS)
        init.update({k: v for k, v in settings.items() if k in DEFAULTS and v is not None})
        init.update(design=design, mode=mode, language=language, run_root=str(self.runs_dir / thread_id),
                    iteration=0, blocks=[], assertions=[], history=[], events=[], runs=[], covered=[],
                    llm_model=self.llm_model or "none (deterministic fallbacks)")
        return self._drive(init, thread_id, on_event)

    def respond(self, thread_id: str, action: str = "approve", feedback: str = "",
                on_event: Callable[[dict], None] | None = None) -> dict:
        if not self.status(thread_id)["pending"]:
            raise ValueError(f"session {thread_id} is not waiting for input")
        return self._drive(Command(resume={"action": action, "feedback": feedback}), thread_id, on_event)

    def exists(self, thread_id: str) -> bool:
        return bool(self.graph.get_state(self._config(thread_id)).values)

    def status(self, thread_id: str) -> dict:
        snap = self.graph.get_state(self._config(thread_id))
        v = snap.values or {}
        interrupts = getattr(snap, "interrupts", None) or [i for t in snap.tasks for i in t.interrupts]
        return {
            "session_id": thread_id,
            "exists": bool(v),
            "design": v.get("design"),
            "language": v.get("language", "sv"),
            "mode": v.get("mode"),
            "iteration": v.get("iteration", 0),
            "done": bool(v.get("done")),
            "stop_reason": v.get("stop_reason", ""),
            "plan": v.get("plan", []),
            "assertions": v.get("assertions", []),
            "blocks": v.get("blocks", []),
            "testbench": v.get("testbench", ""),
            "result": dict(v.get("result") or {}),
            "issue": v.get("issue", ""),
            "triage_note": v.get("triage_note", ""),
            "analysis": v.get("analysis", ""),
            "history": v.get("history", []),
            "events": v.get("events", []),
            "runs": v.get("runs", []),
            "llm_model": v.get("llm_model", ""),
            "pending": interrupts[0].value if interrupts else None,
            "settings": {k: v.get(k, d) for k, d in DEFAULTS.items()},
        }

    def list_sessions(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT thread_id, MAX(rowid) FROM checkpoints GROUP BY thread_id ORDER BY MAX(rowid) DESC"
            ).fetchall()
        return [r[0] for r in rows if (self.graph.get_state(self._config(r[0])).values or {}).get("design") in DESIGNS]

    def suite(self, thread_id: str) -> str | None:
        v = self.graph.get_state(self._config(thread_id)).values or {}
        if not v.get("blocks"):
            return None
        return get_design(v["design"]).build_testbench(v["blocks"], v.get("assertions", []), v.get("language", "sv"))

    def run_mutation(self, thread_id: str, workers: int = 4) -> dict:
        v = self.graph.get_state(self._config(thread_id)).values or {}
        tb = self.suite(thread_id)
        if tb is None:
            raise ValueError(f"session {thread_id} has no test suite yet")
        uvm = v.get("language") == "uvm"
        report = run_mutants(get_design(v["design"]), tb, self.runs_dir / thread_id / "mutants",
                             min(workers, 3) if uvm else workers, uvm)
        report["suite_hash"] = _hash(tb)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO mutation_runs VALUES (?, ?, ?, ?)",
                               (thread_id, report["suite_hash"], json.dumps(report), time.time()))
            self._conn.commit()
        return report

    def mutation_report(self, thread_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT suite_hash, report FROM mutation_runs WHERE thread_id = ?", (thread_id,)).fetchone()
        if not row:
            return None
        report = json.loads(row[1])
        tb = self.suite(thread_id)
        report["stale"] = tb is None or _hash(tb) != row[0]
        return report

    def summary(self, thread_id: str) -> dict:
        st = self.status(thread_id)
        res = st["result"]
        mut = self.mutation_report(thread_id)
        return {
            "session_id": thread_id,
            "design": st["design"],
            "mode": st["mode"],
            "language": st["language"],
            "iterations": len(st["history"]),
            "simulations": sum(e["agent"] == "simulator" for e in st["events"]),
            "functional_pct": res.get("functional_pct"),
            "code": {k: c.get("pct") for k, c in (res.get("code") or {}).items()},
            "done": st["done"],
            "stop_reason": st["stop_reason"],
            "assertions_active": sum(a["status"] == "active" for a in st["assertions"]),
            "assertions_dropped": sum(a["status"] == "dropped" for a in st["assertions"]),
            "mutation": None if mut is None else {k: mut.get(k) for k in (
                "caught", "total", "caught_by_assertions", "survived", "score_pct", "stale")},
        }

    def simulate(self, design: str, testbench: str, sources: dict[str, str] | None = None,
                 language: str = "sv") -> dict:
        """Run any testbench against a design, or against replacement sources, and return the parsed result."""
        d = get_design(design)
        res = simulate(self.runs_dir / "adhoc" / uuid.uuid4().hex[:8], sources or d.sources(),
                       testbench, d.dut_hier, language == "uvm").to_dict()
        res["log"] = res["log"][-6000:]
        return res

    @staticmethod
    def designs() -> list[dict]:
        return [{"name": d.name, "title": d.title, "mutants": len(d.mutants), "languages": d.languages()}
                for d in DESIGNS.values()]
