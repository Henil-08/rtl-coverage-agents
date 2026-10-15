"""Text-edit mutants of adder4.sv. They keep the `c` carry vector because the tb covers dut.c."""

from __future__ import annotations

from dataclasses import dataclass

from agent.tb_template import dut_source

SUM_EXPR = "assign sum[i]   = a[i] ^ b[i] ^ c[i];"
CARRY_EXPR = "assign c[i+1]   = (a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]);"


@dataclass(frozen=True)
class Mutant:
    id: str
    category: str
    description: str
    find: str
    replace: str

    def source(self, golden: str | None = None) -> str:
        golden = golden if golden is not None else dut_source()
        if golden.count(self.find) != 1:
            raise ValueError(f"{self.id}: mutation anchor not found exactly once in adder4.sv")
        header = f"// MUTANT {self.id} [{self.category}]: {self.description}\n"
        return header + golden.replace(self.find, self.replace)


MUTANTS: list[Mutant] = [
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

MUTANTS_BY_ID = {m.id: m for m in MUTANTS}


def verdict(parsed: dict) -> str:
    if parsed.get("passed") is False:
        return "caught"
    if parsed.get("passed") is True:
        return "survived"
    return "invalid"
