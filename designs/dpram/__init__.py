from __future__ import annotations

import random
from pathlib import Path

from designs.base import Design, Mutant

ROOT = Path(__file__).resolve().parent

HARNESS_DOC = """\
Signals in scope: clk; en_a, we_a, en_b, we_b; logic [3:0] addr_a, addr_b; logic [7:0] wdata_a, wdata_b,
rdata_a, rdata_b; int errors. Ops are the enum op_e: IDLE, RD, WR.
Drive the RAM only through these tasks. Each one is exactly one clock cycle:
  cycle(op_a, addr_a, data_a, op_b, addr_b, data_b)   both ports at once, e.g. cycle(WR, 4'd3, 8'h55, RD, 4'd3, 8'h00)
  write_a(addr, data)  read_a(addr)  write_b(addr, data)  read_b(addr)  idle()
Inputs change on negedge clk. The RAM captures them on the next posedge and rdata is valid after it,
so a read issued in cycle N is checked against the reference model at the end of cycle N.
A reference model checks every read of a written address and that rdata holds while a port is idle.
Stimulus is the body of a task: task calls, `for` loops with loop-local `int` variables, and `begin/end`.
Use sized literals such as 4'd15 and 8'hFF. At most 64 cycles per iteration."""

READ_A = "if (en_a) rdata_a <= mem[addr_a];"
READ_B = "if (en_b) rdata_b <= mem[addr_b];"
WRITE_A = "if (en_a && we_a) mem[addr_a] <= wdata_a;"
WRITE_B = "if (en_b && we_b && !a_wins) mem[addr_b] <= wdata_b;"
A_WINS = "assign a_wins = en_a && we_a && (addr_a == addr_b);"

MUTANTS = [
    Mutant("M01", "stuck-at-0", "rdata_a[0] stuck at 0", READ_A,
           "if (en_a) rdata_a <= mem[addr_a] & ~DATA_W'(1);"),
    Mutant("M02", "stuck-at-1", "bit 7 of every port B write stuck at 1", WRITE_B,
           "if (en_b && we_b && !a_wins) mem[addr_b] <= wdata_b | DATA_W'(1 << (DATA_W - 1));"),
    Mutant("M03", "stuck-at-0", "we_b stuck at 0, port B never writes", WRITE_B,
           "if (en_b && 1'b0 && !a_wins) mem[addr_b] <= wdata_b;"),
    Mutant("M04", "inverted", "write collision priority inverted, port B wins", A_WINS,
           "assign a_wins = 1'b0;"),
    Mutant("M05", "inverted", "port B is write-first instead of read-first on a collision", READ_B,
           "if (en_b) rdata_b <= (en_a && we_a && addr_a == addr_b) ? wdata_a : mem[addr_b];"),
    Mutant("M06", "stuck-at-0", "top address bit of port A writes stuck at 0", WRITE_A,
           "if (en_a && we_a) mem[{1'b0, addr_a[ADDR_W-2:0]}] <= wdata_a;"),
    Mutant("M07", "off-by-one", "port B reads addr_b + 1", READ_B,
           "if (en_b) rdata_b <= mem[addr_b + 1'b1];"),
    Mutant("M08", "stuck-at-1", "en_a stuck at 1 for reads, rdata_a does not hold", READ_A,
           "rdata_a <= mem[addr_a];"),
    Mutant("M09", "inverted", "we_a inverted", WRITE_A,
           "if (en_a && !we_a) mem[addr_a] <= wdata_a;"),
    Mutant("M10", "off-by-one", "collision compare ignores the top address bit", A_WINS,
           "assign a_wins = en_a && we_a && (addr_a[ADDR_W-2:0] == addr_b[ADDR_W-2:0]);"),
]

PLAN = [
    {"feature": "every idle/read/write combination on the two ports", "coverpoints": ["cp_op_a", "cp_op_b", "cx_ops"]},
    {"feature": "first, last and middle addresses on both ports for reads and writes",
     "coverpoints": ["cp_raddr_a", "cp_waddr_a", "cp_raddr_b", "cp_waddr_b"]},
    {"feature": "data patterns 0x00, 0xFF, 0xAA/0x55", "coverpoints": ["cp_wdata_a", "cp_wdata_b"]},
    {"feature": "same-address collisions and the port A write priority", "coverpoints": ["cp_conflict"]},
    {"feature": "read right after a write, same port and cross port", "coverpoints": ["cp_raw_a", "cp_raw_b"]},
    {"feature": "every memory bit toggles both ways", "coverpoints": ["toggle"]},
]

ASSERTIONS = """\
a_hold_a: assert property (@(posedge clk) !en_a |=> $stable(rdata_a));
a_hold_b: assert property (@(posedge clk) !en_b |=> $stable(rdata_b));
a_raw_a: assert property (@(posedge clk) (en_a && we_a) ##1 (en_a && !we_a && addr_a == $past(addr_a)) |=> rdata_a == $past(wdata_a, 2));
a_raw_b: assert property (@(posedge clk) (en_b && we_b && !(en_a && we_a && addr_a == addr_b)) ##1 (en_b && !we_b && addr_b == $past(addr_b)) |=> rdata_b == $past(wdata_b, 2));
a_ww_a_wins: assert property (@(posedge clk) (en_a && we_a && en_b && we_b && addr_a == addr_b) ##1 (en_b && !we_b && addr_b == $past(addr_b)) |=> rdata_b == $past(wdata_a, 2));
"""

# Directed snippets for the no-LLM generator, keyed by the coverpoints they close.
LIBRARY: list[tuple[tuple[str, ...], str, str]] = [
    (("cp_op_a", "cp_op_b", "cx_ops"), "all op pairs on distinct addresses", """\
cycle(IDLE, 4'd0, 8'h00, IDLE, 4'd0, 8'h00);
cycle(IDLE, 4'd0, 8'h00, WR, 4'd2, 8'h12);
cycle(IDLE, 4'd0, 8'h00, RD, 4'd2, 8'h00);
cycle(WR, 4'd1, 8'h21, IDLE, 4'd0, 8'h00);
cycle(RD, 4'd1, 8'h00, IDLE, 4'd0, 8'h00);
cycle(WR, 4'd4, 8'h34, WR, 4'd5, 8'h45);
cycle(RD, 4'd4, 8'h00, RD, 4'd5, 8'h00);
cycle(WR, 4'd6, 8'h56, RD, 4'd4, 8'h00);
cycle(RD, 4'd6, 8'h00, WR, 4'd7, 8'h67);"""),
    (("cp_raddr_a", "cp_waddr_a", "cp_raddr_b", "cp_waddr_b"), "first, last and middle addresses", """\
write_a(4'd0, 8'h10);
write_a(4'd15, 8'h1F);
write_b(4'd0, 8'h20);
write_b(4'd15, 8'h2F);
write_b(4'd9, 8'h29);
read_a(4'd0);
read_a(4'd15);
read_a(4'd9);
read_b(4'd0);
read_b(4'd15);
read_b(4'd8);"""),
    (("cp_wdata_a", "cp_wdata_b"), "data patterns", """\
write_a(4'd10, 8'h00);
write_a(4'd11, 8'hFF);
write_a(4'd12, 8'hAA);
write_a(4'd13, 8'h3C);
write_b(4'd10, 8'h00);
write_b(4'd11, 8'hFF);
write_b(4'd12, 8'h55);
write_b(4'd13, 8'hC3);"""),
    (("cp_conflict",), "same-address collisions", """\
write_a(4'd3, 8'h33);
cycle(RD, 4'd3, 8'h00, RD, 4'd3, 8'h00);
cycle(WR, 4'd3, 8'hA3, RD, 4'd3, 8'h00);
cycle(RD, 4'd3, 8'h00, WR, 4'd3, 8'hB3);
cycle(WR, 4'd3, 8'hA4, WR, 4'd3, 8'hB4);
read_b(4'd3);"""),
    (("cp_raw_a", "cp_raw_b"), "read right after write, same and cross port", """\
write_a(4'd5, 8'h5A);
read_a(4'd5);
write_a(4'd6, 8'h6A);
read_b(4'd6);
write_b(4'd7, 8'h7B);
read_a(4'd7);
write_b(4'd8, 8'h8B);
read_b(4'd8);"""),
]

TOGGLE_MARCH = """\
for (int i = 0; i < 16; i++) write_a(i[3:0], 8'h00);
for (int i = 0; i < 16; i++) write_b(i[3:0], 8'hFF);
for (int i = 0; i < 16; i++) read_a(i[3:0]);
for (int i = 0; i < 16; i++) write_a(i[3:0], 8'h00);
for (int i = 0; i < 16; i++) read_b(i[3:0]);"""


def fallback(iteration: int, bins: dict[str, int], blocks: list[dict], code: dict | None = None) -> tuple[str, str]:
    used = {blk.get("focus") for blk in blocks}
    open_points = {k.split(".")[0] for k, v in bins.items() if v == 0} if bins else None
    picks = []
    for points, focus, stim in LIBRARY:
        if focus in used:
            continue
        if open_points is None or open_points & set(points):
            picks.append((focus, stim))
        if len(picks) == 2:
            break
    if not picks:
        toggle = (code or {}).get("toggle") or {}
        if "toggle march" not in used and toggle.get("pct") not in (None, 100.0):
            return "toggle march", TOGGLE_MARCH
        picks = [(f, s) for _, f, s in LIBRARY[:1]]
    return " + ".join(f for f, _ in picks), "\n".join(s for _, s in picks)


def random_stimulus(rng: random.Random, n: int) -> str:
    ops = ("IDLE", "RD", "WR")
    lines = []
    for _ in range(n):
        lines.append(
            f"cycle({rng.choice(ops)}, 4'd{rng.randrange(16)}, 8'h{rng.randrange(256):02X}, "
            f"{rng.choice(ops)}, 4'd{rng.randrange(16)}, 8'h{rng.randrange(256):02X});"
        )
    return "\n".join(lines)


DESIGN = Design(
    name="dpram",
    title="True dual-port RAM (8-bit x 16)",
    root=ROOT,
    rtl_files=("dpram.sv",),
    drivers=("cycle", "write_a", "read_a", "write_b", "read_b", "idle"),
    harness_doc=HARNESS_DOC,
    mutants=MUTANTS,
    default_plan=PLAN,
    default_assertions=ASSERTIONS,
    fallback=fallback,
    random_stimulus=random_stimulus,
)
