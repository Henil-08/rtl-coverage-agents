"""Small HTML components for the Streamlit app."""

from __future__ import annotations

from html import escape

import streamlit as st

AGENTS = [
    ("planner", "Planner", "spec → plan"),
    ("assertion_writer", "Assertions", "spec → SVA"),
    ("stimulus_writer", "Stimulus", "gaps → test"),
    ("simulator", "Simulator", "Verilator"),
    ("triage", "Triage", "route failures"),
    ("coverage_analyst", "Analyst", "next target / stop"),
]

_PALETTE = {
    "light": {
        "ink": "#1C1B19", "muted": "#6B675E", "line": "#DDDAD0", "card": "#FFFFFF", "sunk": "#EFEDE6",
        "accent": "#0F766E", "accent-soft": "rgba(15,118,110,.10)",
        "good": "#15803D", "warn": "#B45309", "bad": "#B91C1C", "s1": "#2a78d6", "s2": "#eb6834",
    },
    "dark": {
        "ink": "#E8E6E1", "muted": "#9A968C", "line": "#2A2E33", "card": "#171A1E", "sunk": "#14171A",
        "accent": "#2DD4BF", "accent-soft": "rgba(45,212,191,.12)",
        "good": "#4ADE80", "warn": "#FBBF24", "bad": "#F87171", "s1": "#3987e5", "s2": "#d95926",
    },
}

_CSS = """
<style>
:root {{ {vars} }}
.block-container {{ padding-top: 3.6rem; max-width: 1280px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.hero {{ display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap; margin-bottom:1.1rem; }}
.hero h1 {{ font-size:1.85rem; margin:0; padding:0; }}
.hero p {{ color:var(--muted); margin:.25rem 0 0; }}
.chips {{ display:flex; gap:.4rem; flex-wrap:wrap; }}
.chip {{ font:500 .75rem/1 'IBM Plex Mono', monospace; padding:.35rem .6rem; border-radius:999px;
        border:1px solid var(--line); color:var(--muted); background:var(--card); white-space:nowrap; }}
.chip.accent {{ color:var(--accent); border-color:var(--accent); background:var(--accent-soft); }}
.chip.good {{ color:var(--good); border-color:var(--good); }}
.chip.warn {{ color:var(--warn); border-color:var(--warn); }}
.chip.bad {{ color:var(--bad); border-color:var(--bad); }}

.pipe {{ display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:.6rem; margin:.4rem 0 1.2rem; }}
.stage {{ position:relative; background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:.75rem .8rem .8rem; min-height:118px; }}
.stage:not(:last-child)::after {{ content:''; position:absolute; right:-.62rem; top:1.35rem; width:.6rem;
          height:2px; background:var(--line); }}
.stage .num {{ font:500 .7rem 'IBM Plex Mono', monospace; color:var(--muted); }}
.stage .name {{ font:600 .98rem 'Space Grotesk', sans-serif; margin-top:.1rem; }}
.stage .role {{ font-size:.75rem; color:var(--muted); }}
.stage .note {{ font-size:.76rem; margin-top:.45rem; color:var(--ink); opacity:.85;
                display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }}
.stage .dot {{ position:absolute; top:.8rem; right:.8rem; width:.55rem; height:.55rem; border-radius:50%; background:var(--line); }}
.stage.done .dot {{ background:var(--good); }}
.stage.warn .dot {{ background:var(--warn); }}
.stage.bad {{ border-color:var(--bad); }}
.stage.bad .dot {{ background:var(--bad); }}
.stage.active {{ border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }}
.stage.active .dot {{ background:var(--accent); animation:pulse 1.1s ease-in-out infinite; }}
@keyframes pulse {{ 50% {{ opacity:.25; }} }}

.legend {{ display:flex; gap:1rem; flex-wrap:wrap; font-size:.75rem; color:var(--muted); margin:-.6rem 0 1.1rem; }}
.legend i {{ display:inline-block; width:.5rem; height:.5rem; border-radius:50%; margin-right:.35rem; vertical-align:middle; }}
.kpis {{ display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:.6rem; margin-bottom:1.2rem; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:.75rem .85rem; }}
.kpi .label {{ font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }}
.kpi .value {{ font:600 1.55rem 'IBM Plex Mono', monospace; margin:.15rem 0 .35rem; }}
.kpi .sub {{ font-size:.75rem; color:var(--muted); }}
.bar {{ height:5px; border-radius:3px; background:var(--sunk); overflow:hidden; }}
.bar > span {{ display:block; height:100%; background:var(--accent); border-radius:3px; }}
.bar > span.full {{ background:var(--good); }}

.feed {{ border-left:2px solid var(--line); margin:.3rem 0 0 .35rem; padding-left:1rem; }}
.ev {{ position:relative; padding:.3rem 0 .55rem; }}
.ev::before {{ content:''; position:absolute; left:-1.35rem; top:.62rem; width:.55rem; height:.55rem;
               border-radius:50%; background:var(--card); border:2px solid var(--muted); }}
.ev.llm::before {{ border-color:var(--accent); }}
.ev.tool::before {{ border-color:var(--s1); }}
.ev.human::before {{ border-color:var(--s2); background:var(--s2); }}
.ev.fallback::before {{ border-color:var(--warn); }}
.ev .head {{ font:500 .78rem 'IBM Plex Mono', monospace; color:var(--muted); }}
.ev .head b {{ color:var(--ink); font-weight:600; }}
.ev .body {{ font-size:.86rem; margin-top:.1rem; }}

.design-card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1rem 1.1rem; height:100%; }}
.design-card h4 {{ margin:0 0 .3rem; font-family:'Space Grotesk', sans-serif; }}
.design-card p {{ color:var(--muted); font-size:.86rem; margin:0; }}
.st-key-gate {{ border:1px solid var(--accent) !important; background:var(--accent-soft); border-radius:12px; padding:1rem 1.1rem; }}
.empty {{ color:var(--muted); font-size:.9rem; padding:1rem 0; }}
@media (max-width: 900px) {{
  .pipe, .kpis {{ grid-template-columns:repeat(2, minmax(0,1fr)); }}
  .stage:not(:last-child)::after {{ display:none; }}
}}
</style>
"""


def theme() -> str:
    t = getattr(getattr(st.context, "theme", None), "type", None)
    return t if t in _PALETTE else "light"


def inject_css() -> None:
    vars_ = " ".join(f"--{k}:{v};" for k, v in _PALETTE[theme()].items())
    st.html(_CSS.format(vars=vars_))


def chip(text: str, tone: str = "") -> str:
    return f'<span class="chip {tone}">{escape(text)}</span>'


def hero(title: str, subtitle: str, chips: list[str]) -> None:
    st.html(f'<div class="hero"><div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>'
            f'<div class="chips">{"".join(chips)}</div></div>')


def pipeline_html(events: list[dict], running: bool = False, issue: str = "") -> str:
    last: dict[str, dict] = {}
    for e in events:
        last[e["agent"]] = e
    latest = events[-1]["agent"] if events else None
    cells = []
    for i, (key, name, role) in enumerate(AGENTS, 1):
        e = last.get(key)
        state = ""
        if e:
            state = "warn" if e["kind"] == "fallback" else "done"
            if key == "triage" and issue == "design_mismatch":
                state = "bad"
        if running and key == latest:
            state = "active"
        note = escape(e["summary"]) if e else "waiting"
        cells.append(f'<div class="stage {state}"><div class="dot"></div><div class="num">0{i}</div>'
                     f'<div class="name">{name}</div><div class="role">{role}</div><div class="note">{note}</div></div>')
    legend = ('<div class="legend"><span><i style="background:var(--good)"></i>done</span>'
              '<span><i style="background:var(--warn)"></i>used the no-LLM fallback</span>'
              '<span><i style="background:var(--bad)"></i>found a problem</span>'
              '<span><i style="background:var(--accent)"></i>running now</span></div>')
    return f'<div class="pipe">{"".join(cells)}</div>{legend}'


def kpis_html(items: list[tuple[str, str, float | None, str]]) -> str:
    cards = []
    for label, value, pct, sub in items:
        bar = ""
        if pct is not None:
            full = " full" if pct >= 100 else ""
            bar = f'<div class="bar"><span class="{full}" style="width:{max(0, min(pct, 100)):.1f}%"></span></div>'
        cards.append(f'<div class="kpi"><div class="label">{escape(label)}</div><div class="value">{escape(value)}</div>'
                     f'{bar}<div class="sub">{escape(sub)}</div></div>')
    return f'<div class="kpis">{"".join(cards)}</div>'


def feed_html(events: list[dict], limit: int = 40) -> str:
    if not events:
        return '<div class="empty">No agent activity yet.</div>'
    rows = []
    for e in reversed(events[-limit:]):
        rows.append(f'<div class="ev {escape(e["kind"])}"><div class="head">it {e.get("iteration", 0)} · '
                    f'<b>{escape(e["agent"])}</b> · {escape(e["kind"])}</div>'
                    f'<div class="body">{escape(e["summary"])}</div></div>')
    return f'<div class="feed">{"".join(rows)}</div>'
