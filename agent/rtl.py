"""Facts about a design read from its RTL with Verilator, so agents never guess pin names or widths."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

CLOCK_NAMES = re.compile(r"^(clk|clock|i_clk|clk_i|aclk|pclk|hclk)$|clk$", re.I)
RESET_NAMES = re.compile(r"^(rst|reset|rst_n|reset_n|arst|arst_n|areset|aresetn|rst_ni|rstn)$", re.I)


class RtlError(Exception):
    pass


def lint(sources: dict[str, str], top: str | None = None) -> list[str]:
    """Verilator lint. Returns error lines (warnings are ignored)."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in sources.items():
            (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / name).write_text(text)
        cmd = ["verilator", "--lint-only", "-Wno-fatal", "-Wno-lint", "-Wno-style", *sources]
        if top:
            cmd += ["--top-module", top]
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=60)
    return [line for line in (proc.stdout + proc.stderr).splitlines() if line.startswith("%Error")]


def _walk(node, pred, out):
    if isinstance(node, dict):
        if pred(node):
            out.append(node)
        for v in node.values():
            _walk(v, pred, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, pred, out)
    return out


def ports(sources: dict[str, str], top: str | None = None) -> dict:
    """Top module name, its ports (name, direction, width) and the likely clock and reset."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in sources.items():
            (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / name).write_text(text)
        cmd = ["verilator", "--json-only", "-Wno-fatal", "-Wno-lint", "-Wno-style", "--Mdir", "json", *sources]
        if top:
            cmd += ["--top-module", top]
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=60)
        trees = list((Path(tmp) / "json").glob("*.tree.json"))
        if proc.returncode != 0 or not trees:
            errors = [l for l in (proc.stdout + proc.stderr).splitlines() if l.startswith("%Error")]
            raise RtlError("\n".join(errors) or proc.stderr.strip() or "verilator could not read the RTL")
        tree = json.loads(trees[0].read_text())

    dtypes = {d["addr"]: d for d in _walk(tree, lambda n: n.get("type", "").endswith("DTYPE") and "addr" in n, [])}
    tops = [m for m in _walk(tree, lambda n: n.get("type") == "MODULE", []) if m.get("level") == 1]
    if not tops:
        raise RtlError("no top module found")
    mod = tops[0]
    out = []
    for var in _walk(mod, lambda n: n.get("type") == "VAR" and n.get("direction") in ("INPUT", "OUTPUT", "INOUT"), []):
        rng = dtypes.get(var.get("dtypep"), {}).get("range")
        width = 1
        if rng:
            hi, lo = (int(x) for x in rng.split(":"))
            width = abs(hi - lo) + 1
        out.append({"name": var["name"], "dir": var["direction"].lower(), "width": width})
    clock = next((p["name"] for p in out if p["dir"] == "input" and p["width"] == 1 and CLOCK_NAMES.search(p["name"])), None)
    reset = next((p["name"] for p in out if p["dir"] == "input" and p["width"] == 1 and RESET_NAMES.match(p["name"])), None)
    return {"top": mod.get("origName") or mod["name"], "ports": out, "clock": clock, "reset": reset}
