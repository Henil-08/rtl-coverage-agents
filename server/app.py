"""HTTP + WebSocket API for the React frontend.

    uv run python -m server          # http://localhost:8000 (serves frontend/dist when it has been built)
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import events, report, rtl
from agent import wave as W
from agent.llm import get_llm
from agent.service import VerificationService
from agent.sim import UVM_SRC, verilator_available
from agent.state import DEFAULTS, MODES
from agent.tbgen import design_for
from designs import all_designs, get_design, user
from rag import kb

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "dist"


class Hub:
    """Fans live events out to every WebSocket watching a session, with a replay buffer for late joiners."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.backlog: dict[str, deque] = {}
        self.running: set[str] = set()

    def publish(self, sid: str, event: dict) -> None:
        self.backlog.setdefault(sid, deque(maxlen=4000)).append(event)
        if self.loop is None:
            return
        for q in list(self.subscribers.get(sid, ())):
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    def run(self, sid: str, job) -> None:
        """Run a blocking service call in a thread, publishing its events under sid."""
        if sid in self.running:
            raise HTTPException(409, "this session is already running")
        self.running.add(sid)
        self.backlog[sid] = deque(maxlen=4000)
        self.publish(sid, {"type": "running"})

        def work():
            token = events.install(lambda e: self.publish(sid, e))
            try:
                job(lambda e: self.publish(sid, e))
            except Exception as e:
                self.publish(sid, {"type": "error", "message": f"{type(e).__name__}: {e}"})
            finally:
                events.remove(token)
                self.running.discard(sid)
                self.publish(sid, {"type": "idle"})

        threading.Thread(target=work, daemon=True).start()


hub = Hub()
_svc: VerificationService | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="rtl-coverage-agents", lifespan=lifespan)


def svc() -> VerificationService:
    global _svc
    if _svc is None:
        _svc = VerificationService(llm=get_llm())
    return _svc


def _trim_status(st: dict) -> dict:
    st = dict(st)
    st["result"] = {k: v for k, v in (st.get("result") or {}).items() if k != "log"}
    st["running"] = st["session_id"] in hub.running
    return st


# ----------------------------------------------------------------------------------------- config

@app.get("/api/config")
def config() -> dict:
    base = kb.load()
    llm = svc().llm_model
    return {
        "llm": None if not llm or llm.startswith("none") else llm,
        "verilator": verilator_available(),
        "uvm": (UVM_SRC / "uvm_pkg.sv").exists(),
        "kb": None if base is None else {"passages": len(base.chunks), "documents": len(base.stats()["docs"]),
                                         "embeddings": base.vectors is not None},
        "defaults": DEFAULTS,
        "modes": list(MODES),
    }


# ---------------------------------------------------------------------------------------- designs

@app.get("/api/designs")
def designs() -> list[dict]:
    return svc().designs()


@app.get("/api/designs/{name}")
def design(name: str) -> dict:
    try:
        d = get_design(name)
    except KeyError:
        raise HTTPException(404, f"no design {name}")
    try:
        info = rtl.ports(d.sources(), d.extra.get("top"))
    except rtl.RtlError as e:
        info = {"error": str(e)}
    return {
        "name": d.name, "title": d.title, "kind": d.kind, "spec": d.spec(), "rtl": d.sources(),
        "ports": info, "languages": d.languages(), "handwritten_tb": d.has_handwritten_tb(),
        "covergroup": d.covergroup(),
        "mutants": [{"id": m.id, "category": m.category, "description": m.description} for m in d.mutants],
    }


@app.post("/api/designs")
async def upload(name: str = Form(...), title: str = Form(""), top: str = Form(""),
                 rtl_files: list[UploadFile] = File(...), spec_file: UploadFile = File(...)) -> dict:
    sources = {f.filename: (await f.read()).decode("utf-8", "replace") for f in rtl_files}
    raw = await spec_file.read()
    try:
        d = user.create(name, sources, user.spec_text(spec_file.filename, raw), title=title, top=top or None,
                        spec_original=(spec_file.filename, raw) if spec_file.filename.lower().endswith(".pdf") else None)
    except (ValueError, rtl.RtlError) as e:
        raise HTTPException(400, str(e))
    return {"name": d.name, "mutants": len(d.mutants)}


@app.delete("/api/designs/{name}")
def delete_design(name: str) -> dict:
    if name not in user.names():
        raise HTTPException(400, "only uploaded designs can be deleted")
    user.delete(name)
    return {"deleted": name}


# --------------------------------------------------------------------------------------- sessions

class StartRequest(BaseModel):
    design: str
    mode: str = "auto"
    language: str = "sv"
    tb_source: str = "handwritten"
    use_kb: bool = True
    target_pct: float | None = None
    toggle_target: float | None = None
    max_iters: int | None = None
    plateau_iters: int | None = None
    plateau_delta: float | None = None


class Answer(BaseModel):
    action: str = "approve"
    feedback: str = ""


@app.get("/api/sessions")
def sessions() -> list[dict]:
    out = []
    for sid in svc().list_sessions():
        st = svc().status(sid)
        out.append({k: st.get(k) for k in ("session_id", "design", "mode", "language", "tb_source", "iteration",
                                           "done", "stop_reason")}
                   | {"functional_pct": st["result"].get("functional_pct"), "waiting": bool(st["pending"]),
                      "running": sid in hub.running})
    return out


@app.post("/api/sessions")
def start(req: StartRequest) -> dict:
    if req.design not in all_designs():
        raise HTTPException(404, f"no design {req.design}")
    sid = f"{req.design}-{uuid.uuid4().hex[:6]}"
    settings = req.model_dump(exclude={"design", "mode", "language"})
    hub.run(sid, lambda sink: svc().start(req.design, req.mode, thread_id=sid, language=req.language,
                                          on_event=sink, **settings))
    return {"session_id": sid}


@app.get("/api/sessions/{sid}")
def session(sid: str) -> dict:
    if not svc().exists(sid) and sid not in hub.running:
        raise HTTPException(404, f"no session {sid}")
    if not svc().exists(sid):
        return {"session_id": sid, "exists": False, "running": True}
    st = _trim_status(svc().status(sid))
    st["mutation"] = svc().mutation_report(sid)
    return st


@app.post("/api/sessions/{sid}/respond")
def respond(sid: str, answer: Answer) -> dict:
    if not svc().status(sid)["pending"]:
        raise HTTPException(409, "the session is not waiting for input")
    hub.run(sid, lambda sink: svc().respond(sid, answer.action, answer.feedback, on_event=sink))
    return {"ok": True}


@app.post("/api/sessions/{sid}/mutation")
def mutation(sid: str) -> dict:
    if svc().suite(sid) is None:
        raise HTTPException(409, "the session has no test suite yet")

    def job(sink):
        rep = svc().run_mutation(sid)
        sink({"type": "mutation_done", "report": {k: v for k, v in rep.items() if k != "results"}})

    hub.run(sid, job)
    return {"ok": True}


@app.get("/api/sessions/{sid}/report.md", response_class=PlainTextResponse)
def report_md(sid: str) -> str:
    st = svc().status(sid)
    return report.markdown(st, design_for(svc().graph.get_state(svc()._config(sid)).values), svc().mutation_report(sid))


@app.get("/api/sessions/{sid}/bundle.zip")
def bundle(sid: str) -> Response:
    st = svc().status(sid)
    data = report.bundle(st, design_for(svc().graph.get_state(svc()._config(sid)).values),
                         svc().mutation_report(sid), svc().suite(sid) or "")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{sid}.zip"'})


# -------------------------------------------------------------------------------------- waveforms

def _wave_path(sid: str, run: int | None, mutant: str | None) -> tuple[str, list[dict]]:
    if mutant:
        rep = svc().mutation_report(sid) or {}
        m = next((r for r in rep.get("results", []) if r["id"] == mutant), None)
        if not m:
            raise HTTPException(404, f"no mutant {mutant}")
        return m.get("wave", ""), m.get("failures", [])
    runs = svc().status(sid)["runs"]
    r = next((r for r in runs if r["n"] == run), runs[-1] if runs else None)
    if not r:
        raise HTTPException(404, "no runs yet")
    return r.get("wave", ""), r.get("failures", [])


@app.get("/api/sessions/{sid}/wave")
def wave(sid: str, run: int | None = None, mutant: str | None = None, start: int | None = None, count: int = 20,
         signals: str = "") -> dict:
    path, failures = _wave_path(sid, run, mutant)
    if not path or not Path(path).exists():
        raise HTTPException(404, "no waveform")
    d = design_for(svc().graph.get_state(svc()._config(sid)).values)
    w = W.read_vcd(path)
    clock = d.clock if d.clock in w.signals else next((n for n in w.signals if n.endswith(".clk")), d.clock)
    fail_cycles = [W.cycle_of(w, clock, f["time"]) for f in failures]
    available = [n for n in w.names() if n.count(".") == 1 and n != clock] + \
                [n for n in w.names() if n.startswith(d.dut_hier + ".") and n.count(".") == 2]
    chosen = [s for s in signals.split(",") if s in w.signals] or [s for s in d.wave_signals if s in w.signals] \
        or available[:12]
    if start is None:
        start = max(0, fail_cycles[0] - count // 2) if fail_cycles else 0
    return {
        "total_cycles": W.total_cycles(w, clock),
        "start": start,
        "signals": chosen,
        "available": available,
        "failures": [{**f, "cycle": c} for f, c in zip(failures, fail_cycles)],
        "diagram": W.wavedrom(w, chosen, clock, start, count, marks=fail_cycles),
    }


@app.get("/api/sessions/{sid}/wave.vcd")
def wave_file(sid: str, run: int | None = None, mutant: str | None = None) -> FileResponse:
    path, _ = _wave_path(sid, run, mutant)
    if not path or not Path(path).exists():
        raise HTTPException(404, "no waveform")
    return FileResponse(path, filename=f"{sid}_{mutant or f'run{run}'}.vcd")


# --------------------------------------------------------------------------------- knowledge base

@app.get("/api/kb/search")
def kb_search(q: str, k: int = 6) -> list[dict]:
    base = kb.load()
    return [] if base is None else base.search(q, k)


# -------------------------------------------------------------------------------------- live feed

@app.websocket("/api/sessions/{sid}/live")
async def live(ws: WebSocket, sid: str) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    hub.subscribers.setdefault(sid, set()).add(q)
    try:
        if svc().exists(sid):
            await ws.send_json({"type": "snapshot", "status": _trim_status(svc().status(sid))})
        for e in list(hub.backlog.get(sid, ())) if sid in hub.running else []:
            await ws.send_json({**e, "replay": True})
        while True:
            e = await q.get()
            await ws.send_json(e)
            if e["type"] in ("finished", "waiting", "idle") and svc().exists(sid):
                await ws.send_json({"type": "snapshot", "status": _trim_status(svc().status(sid))})
    except WebSocketDisconnect:
        pass
    finally:
        hub.subscribers.get(sid, set()).discard(q)


if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = FRONTEND / path
        return FileResponse(target if path and target.is_file() else FRONTEND / "index.html")
