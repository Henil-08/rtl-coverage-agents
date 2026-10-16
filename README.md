# AI-in-Hardware: coverage-guided verification agent

This is a human-in-the-loop agent that closes functional coverage on a 4-bit SystemVerilog adder
(`rtl/adder4.sv`). The agent writes directed stimulus and SVA assertions. You run them on
EDA Playground (Synopsys VCS, Cadence Xcelium or Siemens Questa) and paste the log back. The agent parses the coverage, decides
what is still missing, and writes the next test. It stops when coverage hits a target, plateaus,
or reaches the iteration limit. A mutation-testing mode then scores the final suite against 10
buggy adders.

The agent never runs a simulator itself. The simulator run is the one manual step.

## Layout

```
rtl/adder4.sv          DUT: ripple-carry adder, cout + signed overflow
agent/tb_template.py   fixed harness: covergroup, reference scoreboard, result markers
agent/nodes.py         LangGraph nodes (generate_test, await_human_input, parse_results, critique_and_loop)
agent/graph.py         graph wiring + shared SQLite checkpointer (data/sessions.sqlite)
agent/parser.py        regex parser for simulator logs, LLM fallback
agent/fallback.py      deterministic generator, used when there is no API key or the LLM output is invalid
agent/service.py       session API used by both the UI and the MCP server
mutation/mutants.py    10 deterministic mutants
mcp_server/server.py   MCP tools
app.py                 Streamlit UI
tests/                 pytest suite + fake simulator (Python mirror of the covergroup)
```

## Setup

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # creates .venv from uv.lock
cp .env.example .env         # put your GROQ_API_KEY in .env
uv run streamlit run app.py
uv run pytest -q
```

Without a Groq key the app still works and uses the deterministic generator in `agent/fallback.py`.

## How the loop works

```
generate_test -> await_human_input (pause) -> parse_results -> critique_and_loop -+-> generate_test
                       ^                           |                              +-> END
                       +---- unreadable paste -----+
       generate_test <---- compile error (same iteration is rebuilt) ----+
```

- **Fixed coverage model.** The covergroup `cg_adder` stays the same in every iteration, so
  coverage numbers can be compared. It covers operand ranges (0 / low / high / 15),
  `cin`, `cout`, overflow, the direction of overflow, the propagate vector, each stage of the
  internal carry chain (`dut.c`), and the crosses `a x b` and `cin x cout`.
- **Cumulative suite.** Each testbench replays the stimulus from every earlier iteration, so the
  coverage the simulator reports is coverage for the whole suite.
- **Reference scoreboard.** `apply()` checks every vector against `a + b + cin` and the overflow
  formula, so bugs are caught even without the generated assertions.
- **False-positive assertions.** If an assertion fires on the golden DUT while the scoreboard is
  clean, that assertion is wrong. It is dropped, and the LLM is told why.
- **Stop rule** (all values can be changed in the sidebar): stop at 95 % coverage, or when the gain
  stays under 1 % for 2 iterations, or after 10 iterations.

## The manual EDA Playground step

For each iteration, the UI (or the `propose_test` MCP tool) gives you `testbench.sv` and `design.sv`.

1. Register a full EDA Playground account with your university email. VCS, Xcelium and Questa
   are only available to validated accounts.
2. Left panel: set **Testbench + Design** to *SystemVerilog/Verilog* and
   **Tools & Simulators** to *Synopsys VCS*. Xcelium and Questa should also work. Leave **Use run.do** unticked.
3. Paste `testbench.sv` into the left editor and `design.sv` into the right editor.
4. Click **Run**. Copy the **whole** log, paste it into the app, and click **Submit results**.

Aldec Riviera-PRO does not work for this project right now. The free EDA Playground license
fails at elaboration with `You do not have a valid license to simulate SystemVerilog assertion module`.

The testbench prints markers that the parser reads, so it does not depend on any simulator's
report format:

```
COV_TOTAL 87.50              overall cg_adder coverage (get_inst_coverage)
COV_POINT cp_carry 66.67     per coverpoint / cross
CHECK_FAIL a=.. b=.. ...     scoreboard mismatch
ASSERT_FAIL a_it2_<name>     SVA failure
TEST PASSED | TEST FAILED
```

If the regex finds no coverage at all, an LLM tries to extract it. If that also fails, the UI
asks you to paste again.

## Mutation testing

Once the loop has a suite, the **Mutation testing** tab lists 10 mutants:

| ID | Class | Bug |
|----|-------|-----|
| M01 | stuck-at-0 | `sum[0]` stuck at 0 |
| M02 | stuck-at-1 | `sum[3]` stuck at 1 |
| M03 | stuck-at-0 | `cout` stuck at 0 |
| M04 | stuck-at-1 | `overflow` stuck at 1 |
| M05 | stuck-at-0 | carry out of bit 1 stuck at 0 |
| M06 | inverted | carry-in inverted |
| M07 | inverted | overflow condition inverted |
| M08 | inverted | generate term `a&b` became `a\|b` |
| M09 | off-by-one | `cout` taken from `c[3]` |
| M10 | off-by-one | overflow from `c[2]^c[3]` |

For each mutant, paste the mutant's `design.sv` together with the **same suite testbench**, run it,
and paste the log. A mutant counts as *caught* on `TEST FAILED`, `CHECK_FAIL` or `ASSERT_FAIL`,
and as *survived* on `TEST PASSED`. Any other log is *invalid*, for example a compile error.
If the suite grows after you record results, those results are marked stale and are not counted.

## MCP tools

```bash
uv run python -m mcp_server.server     # stdio
```

| Tool | What it does |
|------|--------------|
| `propose_test(session_id?, target_pct?, plateau_iters?, plateau_delta?, max_iters?)` | starts a session, or returns the test that is waiting for results |
| `submit_coverage_report(session_id, report)` | parses the log; returns coverage, the critique, and `next_test` or a final `summary` |
| `list_mutants(session_id)` | returns the suite testbench and the 10 mutant designs (a helper so MCP clients can get the mutant sources) |
| `submit_mutation_result(session_id, mutant_id, report)` | returns the verdict and the running mutation score |

Example config for an MCP client:

```json
{
  "mcpServers": {
    "adder4-coverage-agent": {
      "command": "uv",
      "args": ["run", "--directory", "/abs/path/AI-in-Hardware", "python", "-m", "mcp_server.server"],
      "env": { "GROQ_API_KEY": "..." }
    }
  }
}
```

Sessions are stored in `data/sessions.sqlite`, which the Streamlit app also uses. A session
started over MCP shows up in the app's **Resume session** list, and the reverse is also true.

## Limitations

- No simulator runs locally. The tests check the Python side with a fake simulator that mirrors
  the covergroup.
- The markers give coverage per coverpoint, not per bin. The parser also reads bin rows from
  Riviera `acdb report` text if they are pasted, but other simulators' bin reports are not parsed.
