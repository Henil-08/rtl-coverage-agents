"""Minimal VCD reader and WaveDrom rendering for the UI."""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_UNITS = {"s": 10**12, "ms": 10**9, "us": 10**6, "ns": 10**3, "ps": 1, "fs": 10**-3}


@dataclass
class Signal:
    name: str
    width: int
    times: list[int] = field(default_factory=list)
    values: list[str] = field(default_factory=list)

    def at(self, t: int) -> str:
        i = bisect.bisect_right(self.times, t) - 1
        return self.values[i] if i >= 0 else "x"


@dataclass
class Wave:
    signals: dict[str, Signal]
    end: int

    def names(self) -> list[str]:
        return list(self.signals)


def read_vcd(path: str | Path) -> Wave:
    """Times are converted to picoseconds. Signal names are full hierarchical paths."""
    text = Path(path).read_text(errors="replace")
    header, _, body = text.partition("$enddefinitions")
    m = re.search(r"\$timescale\s*(\d+)\s*(\w+)\s*\$end", header)
    scale = int(m.group(1)) * _UNITS.get(m.group(2), 1) if m else 1

    by_code: dict[str, list[Signal]] = {}
    signals: dict[str, Signal] = {}
    scope: list[str] = []
    for tok in re.finditer(r"\$scope\s+\w+\s+(\S+)\s*\$end|\$upscope\s*\$end|\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]*\])?\s*\$end", header):
        if tok.group(1):
            scope.append(tok.group(1))
        elif tok.group(0).startswith("$upscope"):
            scope.pop()
        else:
            width, code, name = int(tok.group(2)), tok.group(3), tok.group(4)
            full = ".".join(scope + [name])
            if full not in signals:
                sig = Signal(full, width)
                signals[full] = sig
                by_code.setdefault(code, []).append(sig)

    t = 0
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("$"):
            continue
        c = line[0]
        if c == "#":
            t = int(line[1:]) * scale
            continue
        if c in "bBrR":
            val, _, code = line[1:].partition(" ")
        else:
            val, code = c, line[1:]
        for sig in by_code.get(code, ()):
            if sig.times and sig.times[-1] == t:
                sig.values[-1] = val
            else:
                sig.times.append(t)
                sig.values.append(val)
    return Wave(signals, t)


def _fmt(val: str, width: int) -> str:
    if width == 1:
        return val
    if any(ch in "xXzZ" for ch in val):
        return "x"
    n = int(val, 2)
    return f"{n:X}" if width > 4 else str(n)


def wavedrom(wave: Wave, signals: list[str], clock: str, start_cycle: int, cycles: int,
             marks: list[int] = (), title: str = "") -> dict:
    """WaveDrom JSON with one column per clock cycle, sampled just after each rising edge."""
    clk = wave.signals[clock]
    edges = [t for t, v in zip(clk.times, clk.values) if v == "1"]
    cols = edges[start_cycle:start_cycle + cycles]
    if not cols:
        return {"signal": []}
    probe = [t + 1 for t in cols]
    rows = [{"name": clock.split(".")[-1], "wave": "p" + "." * (len(cols) - 1)}]
    for name in signals:
        sig = wave.signals.get(name)
        if sig is None:
            continue
        vals = [_fmt(sig.at(t), sig.width) for t in probe]
        if sig.width == 1:
            chars = [v if v in "01" else "x" for v in vals]
            row = {"name": name.split(".")[-1], "wave": "".join(
                c if i == 0 or c != chars[i - 1] else "." for i, c in enumerate(chars))}
        else:
            chars, data = [], []
            for i, v in enumerate(vals):
                if i and v == vals[i - 1]:
                    chars.append(".")
                elif v == "x":
                    chars.append("x")
                else:
                    chars.append("=")
                    data.append(v)
            row = {"name": name.split(".")[-1], "wave": "".join(chars), "data": data}
        rows.append(row)
    if marks:
        hit = {start_cycle + i for i in range(len(cols))} & set(marks)
        rows.append({})
        bits = ["1" if start_cycle + i in hit else "0" for i in range(len(cols))]
        rows.append({"name": "FAIL", "wave": "".join(
            b if i == 0 or b != bits[i - 1] else "." for i, b in enumerate(bits))})
    return {"signal": rows, "head": {"text": title, "tick": start_cycle}, "config": {"hscale": 1}}


def cycle_of(wave: Wave, clock: str, time_ps: int) -> int:
    """Index of the last rising clock edge at or before time_ps."""
    clk = wave.signals[clock]
    edges = [t for t, v in zip(clk.times, clk.values) if v == "1"]
    return max(0, bisect.bisect_right(edges, time_ps) - 1)


def total_cycles(wave: Wave, clock: str) -> int:
    clk = wave.signals[clock]
    return sum(v == "1" for v in clk.values)


def html(diagram: dict, dark: bool = False) -> str:
    skin = "dark" if dark else "default"
    bg = "#111315" if dark else "#ffffff"
    diagram = {**diagram, "config": {**diagram.get("config", {}), "skin": skin}}
    return f"""<div id="w0" style="background:{bg};padding:8px;border-radius:10px;overflow-x:auto"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/wavedrom/3.1.0/skins/{skin}.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/wavedrom/3.1.0/wavedrom.min.js"></script>
<script>WaveDrom.RenderWaveForm(0, {json.dumps(diagram)}, "w");</script>"""
