from __future__ import annotations

import random
import re
from itertools import product
from pathlib import Path

from designs.base import Design, Mutant

ROOT = Path(__file__).resolve().parent

HARNESS_DOC = """\
Signals in scope: logic [3:0] a, b; logic cin; logic [3:0] sum; logic cout, overflow; logic clk; int errors.
Drive inputs only with `apply(ia, ib, ic)`: it drives a/b/cin on negedge clk, waits for posedge,
checks the outputs against a reference model and samples the covergroup.
Stimulus is the body of a task: `apply(...)` calls, `for` loops with loop-local `int` variables,
and `begin/end`. Use sized literals such as 4'd15 and 1'b1. At most 64 vectors per iteration."""

SUM_EXPR = "assign sum[i]   = a[i] ^ b[i] ^ c[i];"
CARRY_EXPR = "assign c[i+1]   = (a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]);"

MUTANTS = [
    Mutant("M01", "stuck-at-0", "sum[0] stuck at 0", SUM_EXPR,
           "assign sum[i]   = (i == 0) ? 1'b0 : (a[i] ^ b[i] ^ c[i]);"),
    Mutant("M02", "stuck-at-1", "sum[3] stuck at 1", SUM_EXPR,
           "assign sum[i]   = (i == 3) ? 1'b1 : (a[i] ^ b[i] ^ c[i]);"),
    Mutant("M03", "stuck-at-0", "cout stuck at 0",
           "assign cout     = c[4];", "assign cout     = 1'b0;"),
    Mutant("M04", "stuck-at-1", "overflow stuck at 1",
           "assign overflow = c[3] ^ c[4];", "assign overflow = 1'b1;"),
    Mutant("M05", "stuck-at-0", "carry out of bit 1 (c[2]) stuck at 0", CARRY_EXPR,
           "assign c[i+1]   = (i == 1) ? 1'b0 : ((a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]));"),
    Mutant("M06", "inverted", "carry-in inverted",
           "assign c[0] = cin;", "assign c[0] = ~cin;"),
    Mutant("M07", "inverted", "overflow condition inverted",
           "assign overflow = c[3] ^ c[4];", "assign overflow = ~(c[3] ^ c[4]);"),
    Mutant("M08", "inverted", "carry generate term a&b replaced by a|b", CARRY_EXPR,
           "assign c[i+1]   = (a[i] | b[i]) | (a[i] & c[i]) | (b[i] & c[i]);"),
    Mutant("M09", "off-by-one", "cout taken from c[3] instead of c[4]",
           "assign cout     = c[4];", "assign cout     = c[3];"),
    Mutant("M10", "off-by-one", "overflow uses c[2]^c[3] instead of c[3]^c[4]",
           "assign overflow = c[3] ^ c[4];", "assign overflow = c[2] ^ c[3];"),
]

PLAN = [
    {"feature": "sum and carry-out match a + b + cin", "coverpoints": ["cp_a", "cp_b", "cp_cin", "cp_cout"]},
    {"feature": "operand corner values and their combinations", "coverpoints": ["cx_a_b"]},
    {"feature": "carry propagates through every stage, including a full ripple", "coverpoints": ["cp_carry", "cp_prop"]},
    {"feature": "signed overflow in both directions", "coverpoints": ["cp_ovf", "cp_ovf_sign"]},
    {"feature": "carry-in with and without carry-out", "coverpoints": ["cx_cin_cout"]},
]

ASSERTIONS = """\
a_sum_ok: assert property (@(posedge clk) {cout, sum} == a + b + cin);
a_ovf_ok: assert property (@(posedge clk) overflow == ((a[3] == b[3]) && (sum[3] != a[3])));
a_max_max: assert property (@(posedge clk) (a == 4'd15 && b == 4'd15 && cin) |-> (sum == 4'd15 && cout));
a_zero_zero: assert property (@(posedge clk) (a == 4'd0 && b == 4'd0 && !cin) |-> (sum == 4'd0 && !cout && !overflow));
"""


def _range_bin(v: int) -> str:
    if v == 0:
        return "zero"
    if v == 15:
        return "max"
    return "low" if v <= 7 else "high"


def bins_hit(a: int, b: int, cin: int) -> set[str]:
    """Bins of cg_adder that one apply(a, b, cin) hits on a correct adder."""
    total = a + b + cin
    s, cout = total & 0xF, total >> 4
    ovf = int((a >> 3) == (b >> 3) and (s >> 3) != (a >> 3))
    carries, c = 0, cin
    for i in range(4):
        ai, bi = (a >> i) & 1, (b >> i) & 1
        c = (ai & bi) | (ai & c) | (bi & c)
        carries |= c << i
    prop = a ^ b
    ra, rb = _range_bin(a), _range_bin(b)
    co = "carry" if cout else "no_carry"
    hit = {
        f"cp_a.{ra}", f"cp_b.{rb}", f"cp_cin.c{cin}", f"cp_cout.{co}",
        f"cp_ovf.{'ovf' if ovf else 'no_ovf'}",
        f"cp_prop.{'none_prop' if prop == 0 else 'all_prop' if prop == 15 else 'partial_prop'}",
        f"cx_a_b.{ra}_x_{rb}", f"cx_cin_cout.c{cin}_x_{co}",
    }
    if (a >> 3, b >> 3, ovf) == (0, 0, 1):
        hit.add("cp_ovf_sign.pos_ovf")
    elif (a >> 3, b >> 3, ovf) == (1, 1, 1):
        hit.add("cp_ovf_sign.neg_ovf")
    if carries == 0:
        hit.add("cp_carry.none")
    if carries == 0xF:
        hit.add("cp_carry.full_ripple")
    hit |= {f"cp_carry.c{i + 1}" for i in range(4) if (carries >> i) & 1}
    return hit


ALL_VECTORS = list(product(range(16), range(16), range(2)))
ALL_BINS = set().union(*(bins_hit(*v) for v in ALL_VECTORS))
_APPLY = re.compile(r"apply\(\s*4'd(\d+)\s*,\s*4'd(\d+)\s*,\s*1'b([01])\s*\)")


def _prior_hits(blocks: list[dict]) -> set[str]:
    hit: set[str] = set()
    for blk in blocks:
        for a, b, c in _APPLY.findall(blk.get("stimulus", "")):
            hit |= bins_hit(int(a), int(b), int(c))
    return hit


def fallback(iteration: int, bins: dict[str, int], blocks: list[dict]) -> tuple[str, str]:
    """Greedy set cover over the Python model of the covergroup."""
    targets = {k for k, v in bins.items() if v == 0} if bins else set(ALL_BINS)
    targets -= _prior_hits(blocks)
    picked = []
    while targets and len(picked) < 12:
        best = max(ALL_VECTORS, key=lambda v: len(bins_hit(*v) & targets))
        gain = bins_hit(*best) & targets
        if not gain:
            break
        picked.append(best)
        targets -= gain
    if not picked:
        picked = [(15, 0, 1), (15, 1, 0), (7, 1, 0), (8, 8, 0)]
    gaps = {k for k, v in bins.items() if v == 0} if bins else ALL_BINS
    names = sorted({k.split(".")[0] for k in gaps})
    focus = "greedy cover of " + (", ".join(names[:5]) if names else "carry chain")
    return focus, "\n".join(f"apply(4'd{a}, 4'd{b}, 1'b{c});" for a, b, c in picked)


def random_stimulus(rng: random.Random, n: int) -> str:
    return "\n".join(f"apply(4'd{rng.randrange(16)}, 4'd{rng.randrange(16)}, 1'b{rng.randrange(2)});" for _ in range(n))


DESIGN = Design(
    name="adder4",
    title="4-bit ripple-carry adder",
    root=ROOT,
    rtl_files=("adder4.sv",),
    driver="apply",
    harness_doc=HARNESS_DOC,
    mutants=MUTANTS,
    default_plan=PLAN,
    default_assertions=ASSERTIONS,
    fallback=fallback,
    random_stimulus=random_stimulus,
)
