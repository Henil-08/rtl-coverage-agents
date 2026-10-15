"""Non-LLM test generator. Mirrors cg_adder in Python and greedily picks vectors."""

from __future__ import annotations

import re
from itertools import product

from agent.tb_template import COVERAGE_MODEL


def _range_bin(v: int) -> str:
    if v == 0:
        return "zero"
    if v == 15:
        return "max"
    return "low" if v <= 7 else "high"


def bins_hit(a: int, b: int, cin: int) -> set[str]:
    total = a + b + cin
    s = total & 0xF
    cout = total >> 4
    ovf = int(((a >> 3) & 1) == ((b >> 3) & 1) and ((s >> 3) & 1) != ((a >> 3) & 1))
    carries, c = 0, cin
    for i in range(4):
        ai, bi = (a >> i) & 1, (b >> i) & 1
        c = (ai & bi) | (ai & c) | (bi & c)
        carries |= c << i
    prop = a ^ b
    ra, rb = _range_bin(a), _range_bin(b)
    hit = {
        f"cp_a.{ra}",
        f"cp_b.{rb}",
        f"cp_cin.c{cin}",
        f"cp_cout.{'carry' if cout else 'no_carry'}",
        f"cp_ovf.{'ovf' if ovf else 'no_ovf'}",
        f"cp_prop.{'none_prop' if prop == 0 else 'all_prop' if prop == 15 else 'partial_prop'}",
        f"cx_a_b.{ra}x{rb}",
        f"cx_cin_cout.c{cin}x{'carry' if cout else 'no_carry'}",
    }
    sign = ((a >> 3) & 1, (b >> 3) & 1, ovf)
    if sign == (0, 0, 1):
        hit.add("cp_ovf_sign.pos_ovf")
    elif sign == (1, 1, 1):
        hit.add("cp_ovf_sign.neg_ovf")
    if carries == 0:
        hit.add("cp_carry.none")
    if carries == 0xF:
        hit.add("cp_carry.full_ripple")
    for i in range(4):
        if (carries >> i) & 1:
            hit.add(f"cp_carry.c{i + 1}")
    return hit


ALL_BINS = {f"{cp}.{b}" for cp, bins in COVERAGE_MODEL.items() for b in bins}


def targets_from_results(point_pct: dict[str, float], bins: dict[str, bool]) -> set[str]:
    if not point_pct and not bins:
        return set(ALL_BINS)
    targets = {k for k, v in bins.items() if not v}
    known = {k.split(".")[0] for k in bins}
    for cp, pct in point_pct.items():
        if pct < 100.0 and cp not in known:
            targets |= {f"{cp}.{b}" for b in COVERAGE_MODEL.get(cp, [])}
    return targets


def greedy_vectors(targets: set[str], limit: int = 12) -> list[tuple[int, int, int]]:
    remaining = set(targets)
    picked: list[tuple[int, int, int]] = []
    candidates = list(product(range(16), range(16), range(2)))
    while remaining and len(picked) < limit:
        best = max(candidates, key=lambda v: len(bins_hit(*v) & remaining))
        gain = bins_hit(*best) & remaining
        if not gain:
            break
        picked.append(best)
        remaining -= gain
    return picked


BASE_ASSERTIONS = """\
a_it{n}_sum_ok: assert property (@(posedge clk) {{cout, sum}} == a + b + cin) else begin $error("ASSERT_FAIL a_it{n}_sum_ok"); errors++; end
a_it{n}_ovf_ok: assert property (@(posedge clk) overflow == ((a[3] == b[3]) && (sum[3] != a[3]))) else begin $error("ASSERT_FAIL a_it{n}_ovf_ok"); errors++; end
a_it{n}_max_max: assert property (@(posedge clk) (a == 4'd15 && b == 4'd15 && cin) |-> (sum == 4'd15 && cout)) else begin $error("ASSERT_FAIL a_it{n}_max_max"); errors++; end
a_it{n}_zero_zero: assert property (@(posedge clk) (a == 4'd0 && b == 4'd0 && !cin) |-> (sum == 4'd0 && !cout && !overflow)) else begin $error("ASSERT_FAIL a_it{n}_zero_zero"); errors++; end"""


_APPLY = re.compile(r"apply\(\s*4'd(\d+)\s*,\s*4'd(\d+)\s*,\s*1'b([01])\s*\)")


def prior_hits(blocks: list[dict]) -> set[str]:
    hit: set[str] = set()
    for blk in blocks:
        for a, b, c in _APPLY.findall(blk.get("stimulus", "")):
            hit |= bins_hit(int(a), int(b), int(c))
    return hit


def fallback_block(iteration: int, point_pct: dict[str, float], bins: dict[str, bool], prior: list[dict] = ()) -> dict:
    targets = targets_from_results(point_pct, bins) - prior_hits(list(prior))
    vectors = greedy_vectors(targets)
    if not vectors:
        vectors = [(15, 0, 1), (15, 1, 0), (7, 1, 0), (8, 8, 0)]
    stim = "\n".join(f"apply(4'd{a}, 4'd{b}, 1'b{c});" for a, b, c in vectors)
    named = sorted(targets)[:6]
    focus = "deterministic greedy cover of " + (", ".join(named) + (" ..." if len(targets) > 6 else "") if named else "carry chain")
    return {
        "iteration": iteration,
        "focus": focus,
        "stimulus": stim,
        "assertions": BASE_ASSERTIONS.format(n=iteration) if iteration == 1 else "",
    }
