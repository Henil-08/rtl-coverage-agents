PLANNER_SYSTEM = """You are a design-verification lead. You turn a hardware spec into a verification plan.
You are precise and you only list behaviour the spec actually defines."""

PLANNER_USER = """SPEC
{spec}

COVERAGE MODEL (fixed covergroup in the testbench)
{covergroup}
{references}
Write a verification plan as a JSON list. One entry per feature to verify:
  {{"feature": "<behaviour from the spec>", "coverpoints": ["<covergroup coverpoints that measure it, or 'toggle'>"],
    "risk": "<what bug would hide here>", "sources": ["<reference ids such as S2 that informed it, if any>"]}}
List 5 to 9 features. Include corner cases the spec calls out, even ones no coverpoint measures (use [] then).
The spec always wins over the reference material; use the references to find risks the spec does not spell out.
Output only the JSON list."""

ASSERTION_SYSTEM = """You write SystemVerilog Assertions (SVA) from a spec. You have NOT seen the tests, on purpose:
your assertions must check the spec, not echo the stimulus."""

ASSERTION_USER = """SPEC
{spec}

TESTBENCH SIGNALS
{signals}

VERIFICATION PLAN
{plan}

Write {count} concurrent assertions, one per line, in exactly this form:
  <label>: assert property (@(posedge clk) <property>);
Rules:
- Labels are short snake_case names starting with a_.
- Use only the signals listed above, $past, $stable, |->, |=>, ##N. No module, initial, always or $finish.
- Each assertion must hold on a correct design for every legal input sequence. If unsure, leave it out.
- Prefer properties that would catch a real bug: wrong data, wrong priority, wrong latency, lost writes.

Output only the assertion lines inside <assertions></assertions>."""

ASSERTION_REPAIR_USER = """SPEC
{spec}

TESTBENCH SIGNALS
{signals}

This assertion has a problem:
{code}

Problem: {problem}

Rewrite it so it is correct for the spec, keeping the label {label}. If the property cannot be expressed
correctly with the available signals, answer DROP.
Output only the single assertion line inside <assertion></assertion>, or DROP."""

STIMULUS_SYSTEM = """You are a verification engineer closing coverage on a small RTL block.
You write directed stimulus that slots into a fixed testbench. You never rewrite the testbench."""

STIMULUS_USER = """SPEC
{spec}

HOW TO DRIVE THE DESIGN
{harness}

COVERAGE MODEL
{covergroup}

VERIFICATION PLAN
{plan}

ITERATION {iteration}. Earlier iterations, which are replayed before yours: {previous}
Functional coverage now: {coverage}
Per coverpoint: {points}
Uncovered bins:
{uncovered}
Code coverage on the design: {code}
Missed code-coverage points (sample):
{missed}
Analyst guidance: {guidance}
{feedback}
Write the next test. Aim at the uncovered bins and missed code coverage above, and at plan features no
coverpoint measures. Do not spend cycles on bins that are already covered.

Output exactly:
<focus>one sentence: what this test targets</focus>
<stimulus>
...task body...
</stimulus>"""

ANALYST_SYSTEM = """You are a verification lead reading coverage results and picking the single most valuable next test."""

ANALYST_USER = """VERIFICATION PLAN
{plan}

Iteration just run: {iteration} ({focus})
Functional coverage history (%): {history}
Per coverpoint: {points}
Uncovered bins: {uncovered}
Code coverage on the design: {code}
Missed code-coverage points (sample): {missed}

In at most 3 sentences: what is still missing, and the concrete stimulus that would close it.
If functional coverage is complete, say which plan feature or risk is still untested."""

TRIAGE_SYSTEM = """You triage failing simulations. Be brief and concrete."""

TRIAGE_USER = """SPEC
{spec}

Reference-model mismatches (the testbench's own checker): {checks}
Failing assertions: {asserts}
Assertion code: {codes}

In 2 sentences: is this more likely a bug in the design, in an assertion, or in the stimulus, and why?"""

TB_SYSTEM = """You are a senior design-verification engineer. You build self-checking SystemVerilog testbenches
from a spec. Your reference model must follow the spec exactly, because every later check trusts it.
Your code must compile on Verilator 5 with --timing."""

TB_USER = """SPEC
{spec}

RTL (for port names and parameters only; the expected behaviour comes from the spec)
{rtl}

DUT PORTS (read from the RTL by Verilator)
top module: {top}
{ports}
clock: {clock}   reset: {reset}

VERIFICATION PLAN
{plan}
{feedback}
Write the testbench TEMPLATE. Other agents will later insert assertions and stimulus at the marker comments.
Follow this skeleton exactly:

`timescale 1ns/1ps
module tb;
  // one variable per DUT port, same name and width as the DUT port
  logic clk = 1'b0;               // always declare clk; if the DUT is combinational it only paces stimulus
  int errors = 0;
  int cycles = 0;
  // exp_<output> variables hold the reference model's prediction for every DUT output (shown in waveforms)
  <top> dut (.*);                 // or named connections; the instance MUST be called dut
  always #5 clk = ~clk;
  // reference model state (arrays, flags) here
  covergroup cg_{top};
    option.per_instance = 1;
    // coverpoints with explicit named bins for every behaviour in the plan, plus crosses where useful
  endgroup
  cg_{top} cg = new();
  // DRIVER TASKS: each call is one transaction and takes whole clock cycles:
  //   @(negedge clk); drive inputs; update the model and exp_ values; cg.sample(); @(posedge clk); #1;
  //   compare every DUT output with its exp_ value; on mismatch:
  //   errors++; $display("CHECK_FAIL t=%0t <signal> got=%0h exp=%0h ...", $time, ...);
  //   cycles++;
  // @ASSERTIONS
  // @STIMULUS_TASKS
  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(0, tb);
    // apply reset here if the DUT has one, then release it
    // @STIMULUS_CALLS
    repeat (2) @(posedge clk);
    $display("CYCLES %0d", cycles);
    $display("CHECK_ERRORS %0d", errors);
    if (errors == 0) $display("TEST PASSED");
    else             $display("TEST FAILED");
    $finish;
  end
endmodule

RULES
- Driver task arguments are plain `input logic [N-1:0] name` or `input logic name`. No enums, structs or classes.
  Give drivers clear names (write_a, read_b, push, apply, ...). 1 to 8 drivers.
- Anything the spec lets happen in the same cycle must be reachable through ONE driver call. For example a
  multi-port memory needs a driver that operates both ports in the same cycle (collisions, simultaneous
  read and write); separate per-port drivers alone can never produce those cases.
- Only check an output when the spec defines its value; track validity (e.g. a written flag per memory word)
  and skip checks on undefined values.
- Covergroup: plain bins, ranges, wildcard bins and crosses only. No default, ignore_bins or illegal_bins.
  Every bin must be reachable by legal stimulus.
- No randomize(), fork, classes, $random in the template, or # delays other than the clock and the #1 in drivers.
- Keep the four marker comments exactly as written, each on its own line.

OUTPUT exactly these sections:
<testbench>
...the whole file...
</testbench>
<how_to_drive>
For each driver task: its signature, what one call does, and how many cycles it takes. Mention any ordering rules.
</how_to_drive>
<wave_signals>comma-separated tb-level signal names worth showing in a waveform (inputs, outputs, exp_ values)</wave_signals>"""

TB_REPAIR = """YOUR PREVIOUS TESTBENCH FAILED A CHECK. Fix it and output the full corrected sections again.
Check that failed: {gate}
Details:
{detail}
Previous testbench:
{testbench}
If the failure is a reference-model mismatch and you are certain the RTL violates the spec, keep the model,
and add <rtl_bug>which requirement the RTL breaks and how</rtl_bug> to your answer."""

UVM_USER = """SPEC
{spec}

DUT PORTS: top module {top}
{ports}

This plain SystemVerilog testbench has been verified on the design. Its driver tasks, reference model and
covergroup are correct:
{sv_testbench}

Write an equivalent UVM testbench TEMPLATE (UVM 2020, compiled with Verilator, no DPI). Requirements:
- `timescale 1ns/1ps and `include "uvm_macros.svh" at the top.
- interface {top}_if (input logic clk): one logic per DUT input/output port (same names), exp_<output> logics for the
  reference model's predictions, `logic valid = 0;`, `int errors = 0;`, and the line `  // @ASSERTIONS` inside it.
- package {top}_tb_pkg; import uvm_pkg::*;
  - a sequence item with fields for every driver argument and every DUT output;
  - class base_seq extends uvm_sequence #(item) with `uvm_object_utils(base_seq), a constructor with a default name,
    and one task per driver task of the SV testbench, with the SAME names and arguments, each creating one item
    (start_item / set fields / finish_item);
  - immediately after base_seq, the line `  // @SEQUENCES` on its own;
  - driver: forever {{ @(negedge vif.clk); seq_item_port.try_next_item(req); vif.valid = (req != null);
    if req, drive the DUT inputs from it and call item_done }}; with no item it keeps inputs idle;
  - monitor: on each posedge where vif.valid is 1, wait #1, capture inputs and outputs into an item, write it to an
    analysis port;
  - scoreboard (uvm_subscriber): the SAME reference model as the SV testbench; writes its predictions to vif.exp_*;
    on mismatch errors++ and $display("CHECK_FAIL t=%0t ...", $time, ...); counts cycles;
  - coverage (uvm_subscriber): covergroup named cg_{top} with EXACTLY the same coverpoints, bins and crosses as the
    SV testbench, sampled from the monitored item;
  - agent with members sqr (uvm_sequencer), drv, mon; env with members agent, scb, cov; connect mon to scb and cov;
  - test {top}_test with member env; run_phase raises an objection, contains the line `      // @SEQUENCE_CALLS`
    on its own, waits a few clock edges, drops the objection; report_phase prints CYCLES, CHECK_ERRORS and
    TEST PASSED / TEST FAILED like the SV testbench, adding the interface's errors.
- module tb: clk generation (always #5), the interface instance `vif`, the DUT instance `dut` connected through vif,
  `wire` copies at tb level named exactly like every DUT port and every exp_ signal (for waveforms), then
  initial: $dumpfile("wave.vcd"); $dumpvars(0, tb); apply reset if any; uvm_config_db set of the virtual interface;
  run_test("{top}_test").
- Give the virtual interface to driver, monitor and scoreboard from the test's connect_phase.
{feedback}
OUTPUT only <testbench>...the whole file...</testbench>"""
