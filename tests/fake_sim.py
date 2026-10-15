"""Fake Riviera run: evaluates literal apply() calls and prints the same markers."""

from __future__ import annotations

import re

from agent.fallback import bins_hit
from agent.tb_template import COVERAGE_MODEL

_CROSS_OF = {"cx_a_b": ("cp_a", "cp_b"), "cx_cin_cout": ("cp_cin", "cp_cout")}


def _split_cross(cx: str, name: str) -> tuple[str, str]:
    left, right = _CROSS_OF[cx]
    for x in COVERAGE_MODEL[left]:
        for y in COVERAGE_MODEL[right]:
            if f"{x}x{y}" == name:
                return x, y
    raise KeyError(name)


_APPLY = re.compile(r"apply\(\s*4'd(\d+)\s*,\s*4'd(\d+)\s*,\s*1'b([01])\s*\)")


def simulate(testbench: str, fail_check: bool = False, with_bins: bool = True) -> str:
    vectors = [tuple(int(x) for x in m) for m in _APPLY.findall(testbench)]
    hit: set[str] = set()
    for v in vectors:
        hit |= bins_hit(*v)
    lines = []
    pcts = []
    for cp, bins in COVERAGE_MODEL.items():
        cov = sum(f"{cp}.{b}" in hit for b in bins)
        pct = 100.0 * cov / len(bins)
        pcts.append(pct)
        lines.append(f"# KERNEL: COV_POINT {cp} {pct:.2f}")
    total = sum(pcts) / len(pcts)
    out = [f"# KERNEL: COV_TOTAL {total:.2f}", *lines, f"# KERNEL: VECTORS {len(vectors)}"]
    if fail_check:
        out.append("# KERNEL: CHECK_FAIL a=15 b=1 cin=0 got sum=0 cout=0 ovf=0 exp sum=0 cout=1 ovf=0")
        out += ["# KERNEL: CHECK_ERRORS 1", "# KERNEL: TEST FAILED"]
    else:
        out += ["# KERNEL: CHECK_ERRORS 0", "# KERNEL: TEST PASSED"]
    if with_bins:
        out.append("COVERGROUP COVERAGE")
        for cp, bins in COVERAGE_MODEL.items():
            kind = "CROSS" if cp.startswith("cx") else "CVP"
            out.append(f"| {kind} {cp} |")
            for b in bins:
                name = "<" + ",".join(_split_cross(cp, b)) + ">" if cp.startswith("cx") else b
                h = 1 if f"{cp}.{b}" in hit else 0
                out.append(f"|  bin {name} | {h} | 1 | {'Covered' if h else 'Zero'} |")
    return "\n".join(out)
