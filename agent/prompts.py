GENERATE_SYSTEM = """You are a senior SystemVerilog design-verification engineer doing coverage-closure on a small DUT.
You write directed stimulus and SVA assertions that slot into a FIXED testbench harness. You never rewrite the harness."""

GENERATE_USER = """DUT (design.sv):
```systemverilog
{dut}
```

HARNESS (fixed, already written - you only add code into it):
- Signals in scope: logic [3:0] a, b; logic cin; logic [3:0] sum; logic cout, overflow; logic clk; int errors.
- `apply(ia, ib, ic)` drives a/b/cin on negedge clk, waits for posedge, checks against a reference model, and samples the covergroup.
  It is the ONLY way to drive inputs.
- Fixed covergroup `cg_adder` (coverpoint -> bins):
{model}
  cp_ovf_sign = {{a[3], b[3], overflow}}: pos_ovf=3'b001, neg_ovf=3'b111.
  cp_prop = a ^ b: none_prop=0, partial_prop=1..14, all_prop=15.
  cp_carry = dut.c[4:1] (internal carry chain): none=0000, c1..c4 = that carry bit set (wildcard), full_ripple=1111.
  cx_a_b = cross cp_a x cp_b (16 bins), cx_cin_cout = cross cp_cin x cp_cout (4 bins).
- Every earlier iteration's stimulus is replayed before yours, so coverage is cumulative.

ITERATION: {iteration}
PREVIOUS FOCUSES: {previous}
CURRENT COVERAGE: {coverage}
UNCOVERED / WEAK TARGETS:
{uncovered}
CRITIC GUIDANCE: {guidance}
{feedback}
Write the NEXT test. Target the uncovered behaviour above (carry propagation, overflow, edge inputs such as 0+0 and max+max).
Do not repeat vectors that only hit already-covered bins.

RULES
- Stimulus is the BODY of a SystemVerilog task: only `apply(...)` calls, `for` loops with loop-local `int` variables, and `begin/end`.
  No other declarations, no `#delays`, no `$finish`, no `module`, no `initial`. Use sized literals like 4'd15, 1'b1. At most 64 vectors.
- Assertions are concurrent SVA at module scope, each on one line in exactly this form:
  a_it{iteration}_<name>: assert property (@(posedge clk) <expr>) else begin $error("ASSERT_FAIL a_it{iteration}_<name>"); errors++; end
  Only reference a, b, cin, sum, cout, overflow. They must hold for a CORRECT adder: {{cout,sum}} == a+b+cin and
  overflow == (a[3]==b[3]) && (sum[3]!=a[3]). Write 1-4 assertions that check behaviour your stimulus exercises.

OUTPUT exactly these three tagged sections and nothing else:
<focus>one sentence: what this test targets</focus>
<assertions>
...
</assertions>
<stimulus>
...
</stimulus>
"""

CRITIQUE_SYSTEM = """You are a verification lead reviewing coverage results and choosing the single most valuable next test."""

CRITIQUE_USER = """Coverage model (coverpoint -> bins): {model}
Iteration just run: {iteration}  focus: {focus}
Coverage history (%): {history}
Per-coverpoint coverage: {points}
Uncovered targets: {uncovered}
Assertion failures: {assertion_failures}
Reference-model check failures: {check_failures}

In at most 3 sentences: say what is still missing and name the concrete input vectors (a, b, cin) that the next
test should apply to close it. Be specific; no generic advice."""
