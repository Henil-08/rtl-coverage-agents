from __future__ import annotations

import json
import re
from typing import Any

from langgraph.types import interrupt

from agent import prompts
from agent.fallback import fallback_block
from agent.parser import has_coverage, parse_report, parse_with_llm, uncovered_targets
from agent.state import DEFAULTS, VerifState
from agent.tb_template import COVERAGE_MODEL, EDA_INSTRUCTIONS, build_testbench, dut_source

_TAG = r"<{0}>\s*(.*?)\s*</{0}>"
_FORBIDDEN = re.compile(r"\$finish|\bmodule\b|\binitial\b|\balways\b|#\s*\d")
_ASSERT_LABEL = re.compile(r"^(\s*)(\w+)\s*:\s*assert\b", re.M)


def _cfg(state: VerifState, key: str):
    return state.get(key, DEFAULTS[key])


def _strip_fences(text: str) -> str:
    return re.sub(r"```\w*", "", text).strip()


def _parse_generation(content: str, iteration: int) -> dict | None:
    parts = {}
    for tag in ("focus", "assertions", "stimulus"):
        m = re.search(_TAG.format(tag), content, re.S)
        parts[tag] = _strip_fences(m.group(1)) if m else ""
    stim = parts["stimulus"]
    if "apply(" not in stim or _FORBIDDEN.search(stim):
        return None
    asserts = parts["assertions"]
    if _FORBIDDEN.search(asserts.replace("@(posedge clk)", "")):
        return None
    # labels must be unique across iterations since the tb keeps all of them
    prefix = f"a_it{iteration}_"

    def relabel(m: re.Match) -> str:
        label = m.group(2)
        return f"{m.group(1)}{label if label.startswith(prefix) else prefix + label}: assert"

    asserts = _ASSERT_LABEL.sub(relabel, asserts)
    return {
        "iteration": iteration,
        "focus": parts["focus"] or "LLM-directed test",
        "stimulus": stim,
        "assertions": asserts,
    }


def make_nodes(llm=None) -> dict[str, Any]:
    def generate_test(state: VerifState) -> dict:
        regen = state.get("regenerate", False)
        it = state.get("iteration", 0) if regen else state.get("iteration", 0) + 1
        blocks = [b for b in state.get("blocks", []) if b["iteration"] != it]
        points, bins = state.get("point_pct", {}), state.get("bins", {})

        block, source = None, "fallback"
        if llm is not None:
            feedback = ""
            if regen and state.get("compile_feedback"):
                feedback = f"PREVIOUS ATTEMPT FAILED TO COMPILE, fix it:\n{state['compile_feedback']}\n"
            if state.get("assertion_failures") and not state.get("check_failures"):
                feedback += (
                    "These assertions fired on the CORRECT DUT and were removed (they were wrong): "
                    f"{state['assertion_failures']}\n"
                )
            msg = prompts.GENERATE_USER.format(
                dut=dut_source(),
                model=json.dumps(COVERAGE_MODEL, indent=1),
                iteration=it,
                previous=[b.get("focus", "") for b in blocks] or "none",
                coverage=f"{state['coverage_pct']:.2f}%" if state.get("coverage_pct") is not None else "not run yet",
                uncovered="\n".join(f"- {u}" for u in uncovered_targets(points, bins)) or "- everything (first run)",
                guidance=state.get("next_focus") or "start with edge inputs (0+0, max+max) and full carry ripple",
                feedback=feedback,
            )
            for _ in range(2):
                try:
                    resp = llm.invoke([("system", prompts.GENERATE_SYSTEM), ("user", msg)])
                except Exception:
                    break
                block = _parse_generation(getattr(resp, "content", str(resp)), it)
                if block:
                    source = "llm"
                    break
        if block is None:
            block = fallback_block(it, points, bins, blocks)

        blocks.append(block)
        return {
            "iteration": it,
            "blocks": blocks,
            "testbench": build_testbench(it, blocks),
            "focus": block["focus"],
            "generator": source,
            "regenerate": False,
            "compile_feedback": "",
            "parse_error": "",
        }

    def await_human_input(state: VerifState) -> dict:
        report = interrupt(
            {
                "iteration": state["iteration"],
                "focus": state.get("focus", ""),
                "generator": state.get("generator", ""),
                "testbench": state["testbench"],
                "design": dut_source(),
                "instructions": EDA_INSTRUCTIONS,
                "parse_error": state.get("parse_error", ""),
            }
        )
        return {"raw_report": str(report)}

    def parse_results(state: VerifState) -> dict:
        raw = state.get("raw_report", "")
        parsed = parse_report(raw)
        if not has_coverage(parsed) and llm is not None and raw.strip():
            try:
                parsed = parse_with_llm(raw, llm) or parsed
            except Exception:
                pass

        if not has_coverage(parsed):
            if parsed["compile_errors"]:
                return {
                    "regenerate": True,
                    "compile_feedback": "\n".join(parsed["compile_errors"][:10]),
                    "parse_error": "",
                }
            return {"parse_error": "No coverage data found in the pasted log. Paste the full simulator log."}

        pct = parsed["coverage_pct"]
        if pct is None and parsed["point_pct"]:
            pct = round(sum(parsed["point_pct"].values()) / len(parsed["point_pct"]), 2)
        record = {
            "iteration": state["iteration"],
            "focus": state.get("focus", ""),
            "coverage_pct": pct,
            "passed": parsed["passed"],
            "assertion_failures": parsed["assertion_failures"],
            "check_failures": parsed["check_failures"],
            "parse_source": parsed["parse_source"],
        }
        return {
            "coverage_pct": pct,
            "point_pct": parsed["point_pct"],
            "bins": parsed["bins"],
            "assertion_failures": parsed["assertion_failures"],
            "check_failures": parsed["check_failures"],
            "passed": parsed["passed"],
            "parse_source": parsed["parse_source"],
            "parse_error": "",
            "regenerate": False,
            "history": [record],
        }

    def critique_and_loop(state: VerifState) -> dict:
        blocks = [dict(b) for b in state.get("blocks", [])]
        notes: list[str] = []

        # scoreboard clean but assertion fired -> the assertion is wrong, not the DUT
        if state.get("assertion_failures") and not state.get("check_failures"):
            bad = {int(m) for f in state["assertion_failures"] for m in re.findall(r"a_it(\d+)_", f)}
            for b in blocks:
                if b["iteration"] in bad and b.get("assertions"):
                    b["assertions"] = ""
                    notes.append(f"dropped false-positive assertions from iteration {b['iteration']}")
        if state.get("check_failures"):
            notes.append(f"reference model mismatch on golden DUT: {state['check_failures'][:3]}")

        history = [h for h in state.get("history", []) if h.get("coverage_pct") is not None]
        pct = state.get("coverage_pct") or 0.0
        it = state.get("iteration", 0)
        n, delta = _cfg(state, "plateau_iters"), _cfg(state, "plateau_delta")

        done, reason = False, ""
        if pct >= _cfg(state, "target_pct"):
            done, reason = True, f"target coverage {_cfg(state, 'target_pct'):.1f}% reached ({pct:.2f}%)"
        elif it >= _cfg(state, "max_iters"):
            done, reason = True, f"max iterations ({it}) reached at {pct:.2f}%"
        elif len(history) > n:
            gains = [history[-i]["coverage_pct"] - history[-i - 1]["coverage_pct"] for i in range(1, n + 1)]
            if all(g < delta for g in gains):
                done, reason = True, f"coverage plateaued at {pct:.2f}% (gain < {delta}% for {n} iterations)"

        uncovered = uncovered_targets(state.get("point_pct", {}), state.get("bins", {}))
        next_focus = "close: " + "; ".join(uncovered[:5]) if uncovered else "all coverpoints at 100%"
        if not done and llm is not None:
            try:
                resp = llm.invoke(
                    [
                        ("system", prompts.CRITIQUE_SYSTEM),
                        (
                            "user",
                            prompts.CRITIQUE_USER.format(
                                model=json.dumps(COVERAGE_MODEL),
                                iteration=it,
                                focus=state.get("focus", ""),
                                history=[h["coverage_pct"] for h in history],
                                points=state.get("point_pct", {}),
                                uncovered=uncovered or "none reported",
                                assertion_failures=state.get("assertion_failures", []),
                                check_failures=state.get("check_failures", []),
                            ),
                        ),
                    ]
                )
                next_focus = getattr(resp, "content", str(resp)).strip()
            except Exception:
                pass

        return {
            "blocks": blocks,
            "done": done,
            "stop_reason": reason,
            "critique": "; ".join(notes),
            "next_focus": next_focus,
        }

    return {
        "generate_test": generate_test,
        "await_human_input": await_human_input,
        "parse_results": parse_results,
        "critique_and_loop": critique_and_loop,
    }
