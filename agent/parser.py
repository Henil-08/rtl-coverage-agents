from __future__ import annotations

import json
import re
from typing import Any

from agent.tb_template import COVERAGE_MODEL

_TOTAL = re.compile(r"COV_TOTAL\s+([\d.]+)")
_POINT = re.compile(r"COV_POINT\s+(\w+)\s+([\d.]+)")
_CHECK_FAIL = re.compile(r"CHECK_FAIL.*")
_ASSERT_FAIL = re.compile(r"ASSERT_FAIL.*")
_GENERIC_ASSERT = re.compile(r"(?i)\bassert(?:ion)?\b.*\b(?:fail(?:ed|ure)?|error)\b.*")
_ERRORS_LINE = re.compile(r"CHECK_ERRORS\s+(\d+)")
_PASSED = re.compile(r"\bTEST PASSED\b")
_FAILED = re.compile(r"\bTEST FAILED\b")
_COMPILE_ERR = re.compile(
    r"(?i)\b(?:error|fatal)\b[:\s]+(?:COMP|ELAB|VCP|DAGGEN)\w*.*"
    r"|\b(?:COMP|ELAB|VCP)\w*\s*:?\s*(?:error|fatal)\b.*"
    r"|\berror:\s*\S+\.sv\(\d+\).*"
)
_CG_TOTAL = re.compile(r"(?i)(?:TYPE|covergroup)\b[^\n%]*\bcg_adder\b[^\n%]*?([\d.]+)\s*%")
_CVP_CTX = re.compile(r"\b(cp_\w+|cx_\w+)\b")
_STATUS = re.compile(r"(?i)\b(uncovered|zero|covered)\b")


def _strip_kernel(line: str) -> str:
    return re.sub(r"^\s*#\s*(?:KERNEL|RUNTIME|ASSERT|SIM)?:?\s*", "", line)


def _norm_bin(name: str) -> str:
    # <zero,max> -> zeroxmax
    name = name.strip()
    m = re.fullmatch(r"<\s*(\w+)\s*,\s*(\w+)\s*>", name)
    return f"{m.group(1)}x{m.group(2)}" if m else name


def _parse_bins(lines: list[str]) -> dict[str, bool]:
    bins: dict[str, bool] = {}
    ctx: str | None = None
    for raw in lines:
        line = _strip_kernel(raw)
        tokens = [t for t in re.split(r"[\s|]+", line) if t]
        if not tokens:
            continue
        low = [t.lower() for t in tokens]
        if "bin" not in low:
            m = _CVP_CTX.search(line)
            if m and m.group(1) in COVERAGE_MODEL and re.search(r"(?i)\b(cvp|coverpoint|cross|cross_cvp)\b", line):
                ctx = m.group(1)
            continue
        idx = low.index("bin")
        if idx + 1 >= len(tokens) or ctx is None:
            continue
        name = tokens[idx + 1]
        j = idx + 2
        if name.startswith("<") and not name.endswith(">"):
            while j < len(tokens) and not name.endswith(">"):
                name += tokens[j]
                j += 1
        name = _norm_bin(name)
        if name not in COVERAGE_MODEL[ctx]:
            continue
        # "zero" is both a bin name and a status word, so only look after the name
        rest = tokens[j:]
        status = _STATUS.search(" ".join(rest))
        if status:
            covered = status.group(1).lower() == "covered"
        else:
            nums = [t for t in rest if t.isdigit()]
            covered = bool(nums) and int(nums[0]) > 0
        bins[f"{ctx}.{name}"] = covered
    return bins


def parse_report(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    clean = [_strip_kernel(line) for line in lines]
    joined = "\n".join(clean)

    total: float | None = None
    if m := _TOTAL.search(joined):
        total = float(m.group(1))
    elif m := _CG_TOTAL.search(joined):
        total = float(m.group(1))

    points = {name: float(pct) for name, pct in _POINT.findall(joined)}
    bins = _parse_bins(lines)

    check_failures = [m.group(0).strip() for m in _CHECK_FAIL.finditer(joined)]
    assertion_failures = [m.group(0).strip() for m in _ASSERT_FAIL.finditer(joined)]
    if not assertion_failures:
        assertion_failures = [
            m.group(0).strip()
            for m in _GENERIC_ASSERT.finditer(joined)
            if "ASSERT_FAIL" not in m.group(0)
        ]
    compile_errors = [m.group(0).strip() for m in _COMPILE_ERR.finditer(joined)]

    if _FAILED.search(joined) or check_failures or assertion_failures:
        passed: bool | None = False
    elif _PASSED.search(joined):
        passed = True
    else:
        passed = None

    if total is None and bins:
        total = round(100.0 * sum(bins.values()) / len(bins), 2)

    return {
        "coverage_pct": total,
        "point_pct": points,
        "bins": bins,
        "check_failures": check_failures,
        "assertion_failures": assertion_failures,
        "compile_errors": compile_errors,
        "passed": passed,
        "errors_reported": int(m.group(1)) if (m := _ERRORS_LINE.search(joined)) else None,
        "parse_source": "regex",
    }


def has_coverage(parsed: dict[str, Any]) -> bool:
    return parsed["coverage_pct"] is not None or bool(parsed["point_pct"]) or bool(parsed["bins"])


_LLM_PROMPT = """You extract data from a Riviera-PRO simulation log for a 4-bit adder testbench.
Coverpoints and bins in the coverage model: {model}

Return ONLY a JSON object with keys:
  "coverage_pct": number or null  (overall covergroup coverage percent)
  "point_pct": object mapping coverpoint name -> percent
  "uncovered_bins": list of "coverpoint.bin" strings that are clearly uncovered
  "assertion_failures": list of strings
  "passed": true, false or null
Do not guess numbers that are not in the log; use null / empty instead.

LOG:
{log}
"""


def parse_with_llm(text: str, llm) -> dict[str, Any] | None:
    resp = llm.invoke(_LLM_PROMPT.format(model=json.dumps(COVERAGE_MODEL), log=text[-12000:]))
    content = getattr(resp, "content", str(resp))
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    uncovered = set(data.get("uncovered_bins") or [])
    bins = {}
    for cp, names in COVERAGE_MODEL.items():
        for n in names:
            key = f"{cp}.{n}"
            if key in uncovered:
                bins[key] = False
    pct = data.get("coverage_pct")
    return {
        "coverage_pct": float(pct) if isinstance(pct, (int, float)) else None,
        "point_pct": {k: float(v) for k, v in (data.get("point_pct") or {}).items() if isinstance(v, (int, float))},
        "bins": bins,
        "check_failures": [],
        "assertion_failures": [str(x) for x in data.get("assertion_failures") or []],
        "compile_errors": [],
        "passed": data.get("passed") if isinstance(data.get("passed"), bool) else None,
        "errors_reported": None,
        "parse_source": "llm",
    }


def uncovered_targets(point_pct: dict[str, float], bins: dict[str, bool]) -> list[str]:
    out = [k for k, v in bins.items() if not v]
    known_cps = {k.split(".")[0] for k in bins}
    for cp, pct in point_pct.items():
        if pct < 100.0 and cp not in known_cps:
            out.append(f"{cp} ({pct:.1f}% - bins: {', '.join(COVERAGE_MODEL.get(cp, []))})")
    return out
