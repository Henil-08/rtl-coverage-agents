"""Generic mutants for any RTL: stuck-at, inverted conditions, swapped operators, off-by-one indexes."""

from __future__ import annotations

import re
from itertools import zip_longest

from agent.rtl import lint
from designs.base import Mutant

_SKIP = re.compile(r"^\s*(//|/\*|\*|module\b|endmodule|input\b|output\b|inout\b|logic\b|wire\b|reg\b|parameter\b|"
                   r"localparam\b|genvar\b|typedef\b|`|function\b|endfunction|task\b|endtask|end\b|begin\b|else\s*$)")
_ASSIGN = re.compile(r"^(\s*(?:assign\s+)?[\w\[\]\.:+\- ]+?\s*(?:<=|=)\s*)(.+?)(;\s*(?://.*)?)$")
_IF = re.compile(r"\bif\s*\((.+)\)")
_SWAPS = [("&&", "||"), ("||", "&&"), ("==", "!="), ("!=", "=="), ("<=", "<"), (">=", ">"), (" & ", " | "),
          (" | ", " & "), (" ^ ", " & "), (" + ", " - "), (" - ", " + "), ("1'b0", "1'b1"), ("1'b1", "1'b0")]
_INDEX = re.compile(r"(\w+)\[(\w+)\](?!\s*(?:<=|=))")


def _split_if(line: str) -> tuple[str, str]:
    """`if (cond) x <= y;` -> ("if (cond)", " x <= y;") so the guarded assignment can be mutated too."""
    m = re.search(r"\bif\s*\(", line)
    if not m:
        return "", line
    depth = 0
    for i in range(m.end() - 1, len(line)):
        depth += {"(": 1, ")": -1}.get(line[i], 0)
        if depth == 0:
            return line[:i + 1], line[i + 1:]
    return "", line


def _candidates(file: str, text: str) -> dict[str, list[Mutant]]:
    lines = text.splitlines()
    counts = {l: lines.count(l) for l in lines}
    out: dict[str, list[Mutant]] = {"stuck-at-0": [], "stuck-at-1": [], "inverted": [], "operator": [], "off-by-one": []}
    for n, line in enumerate(lines, 1):
        if counts[line] != 1 or not line.strip() or _SKIP.match(line):
            continue
        where = f"{file}:{n}"
        guard, stmt = _split_if(line)
        m = _ASSIGN.match(stmt)
        if m and "<=" not in m.group(2) and not m.group(2).strip().startswith(("'0", "'1")):
            lhs = m.group(1).split("=")[0].replace("<", "").replace("assign", "").strip()
            for kind, const in (("stuck-at-0", "'0"), ("stuck-at-1", "'1")):
                out[kind].append(Mutant("", kind, f"{lhs} stuck at {const[1]} ({where})", line,
                                        f"{guard}{m.group(1)}{const}{m.group(3)}", file))
        c = _IF.search(line)
        if c:
            out["inverted"].append(Mutant("", "inverted", f"condition `{c.group(1).strip()}` inverted ({where})", line,
                                          line.replace(c.group(0), f"if (!({c.group(1)}))", 1), file))
        body = m.group(2) if m else line
        for old, new in _SWAPS:
            if old in body and not (old == "<=" and m is None):
                repl = line.replace(body, body.replace(old, new, 1), 1) if m else line.replace(old, new, 1)
                if repl != line:
                    out["operator"].append(Mutant("", "operator", f"`{old.strip()}` became `{new.strip()}` ({where})",
                                                  line, repl, file))
        idx = _INDEX.search(body)
        if idx and m:
            new_body = body.replace(idx.group(0), f"{idx.group(1)}[{idx.group(2)} + 1'b1]", 1)
            out["off-by-one"].append(Mutant("", "off-by-one", f"`{idx.group(0)}` reads one entry too far ({where})",
                                            line, line.replace(body, new_body, 1), file))
    return out


def generate(sources: dict[str, str], top: str | None = None, limit: int = 10) -> list[Mutant]:
    """Pick up to `limit` mutants that still compile, spread across fault kinds and lines."""
    pools: dict[str, list[Mutant]] = {}
    for file, text in sources.items():
        for kind, ms in _candidates(file, text).items():
            pools.setdefault(kind, []).extend(ms)
    ordered = [m for group in zip_longest(*pools.values()) for m in group if m is not None]
    picked, used_lines = [], set()
    for m in ordered:
        if len(picked) == limit:
            break
        if (m.file, m.find) in used_lines and len(ordered) > limit * 2:
            continue
        srcs = dict(sources)
        srcs[m.file] = srcs[m.file].replace(m.find, m.replace, 1)
        if lint(srcs, top):
            continue
        used_lines.add((m.file, m.find))
        picked.append(Mutant(f"M{len(picked) + 1:02d}", m.category, m.description, m.find, m.replace, m.file))
    return picked
