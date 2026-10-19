"""Designs uploaded by users: RTL plus a spec, stored under user_designs/ (gitignored)."""

from __future__ import annotations

import io
import json
import re
import shutil
from pathlib import Path

from agent.rtl import RtlError, lint, ports
from designs.base import Design, Mutant
from designs.generic import fallback_for, random_stimulus_for

USER_DIR = Path(__file__).resolve().parent.parent / "user_designs"
NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def spec_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader

        return "\n\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", "replace")


def create(name: str, rtl: dict[str, str], spec: str, title: str = "", top: str | None = None,
           spec_original: tuple[str, bytes] | None = None) -> Design:
    from designs import DESIGNS

    if not NAME.match(name) or name in DESIGNS:
        raise ValueError("name must be 2-41 lowercase letters, digits or underscores, and not a built-in design")
    rtl = {Path(f).name: t for f, t in rtl.items()}
    if not rtl or not all(f.endswith((".sv", ".v", ".svh", ".vh")) for f in rtl):
        raise ValueError("upload at least one .sv or .v file")
    if not spec.strip():
        raise ValueError("the spec is empty")
    errors = lint(rtl, top)
    if errors:
        raise RtlError("\n".join(errors[:10]))
    info = ports(rtl, top)
    root = USER_DIR / name
    if root.exists():
        shutil.rmtree(root)
    (root / "rtl").mkdir(parents=True)
    for fname, text in rtl.items():
        (root / "rtl" / Path(fname).name).write_text(text)
    (root / "spec.md").write_text(spec)
    if spec_original:
        (root / spec_original[0]).write_bytes(spec_original[1])
    from agent.mutate import generate as generate_mutants

    mutants = generate_mutants(rtl, info["top"])
    meta = {"name": name, "title": title or info["top"], "top": info["top"], "ports": info["ports"],
            "clock": info["clock"], "reset": info["reset"], "rtl_files": [Path(f).name for f in rtl],
            "mutants": [m.__dict__ for m in mutants]}
    (root / "meta.json").write_text(json.dumps(meta, indent=1))
    return load(name)


def _plan_from_spec(spec: str) -> list[dict]:
    reqs = re.findall(r"^\s*-\s+(R\d+:.+)$", spec, re.M) or re.findall(r"^\s*-\s+(.+)$", spec, re.M)
    return [{"feature": r.strip(), "coverpoints": []} for r in reqs[:10]] or [{"feature": "behaviour in the spec", "coverpoints": []}]


def load(name: str) -> Design:
    root = USER_DIR / name
    meta = json.loads((root / "meta.json").read_text())
    port_list = ", ".join(f"{p['dir']} [{p['width'] - 1}:0] {p['name']}" if p["width"] > 1 else f"{p['dir']} {p['name']}"
                          for p in meta["ports"])
    return Design(
        name=name,
        title=meta["title"],
        root=root,
        rtl_files=tuple(f"rtl/{f}" for f in meta["rtl_files"]),
        drivers=(),
        harness_doc="",
        signals=f"DUT ports ({meta['top']}): {port_list}",
        mutants=[Mutant(**{**m, "file": m["file"] if m["file"].startswith("rtl/") else f"rtl/{m['file']}"})
                 for m in meta["mutants"]],
        default_plan=_plan_from_spec((root / "spec.md").read_text()),
        default_assertions="",
        fallback=fallback_for([]),
        random_stimulus=random_stimulus_for([]),
        kind="upload",
        extra={"top": meta["top"], "ports": meta["ports"], "clock": meta["clock"], "reset": meta["reset"]},
    )


def names() -> list[str]:
    return sorted(p.name for p in USER_DIR.glob("*") if (p / "meta.json").exists())


def delete(name: str) -> None:
    if name in names():
        shutil.rmtree(USER_DIR / name)
