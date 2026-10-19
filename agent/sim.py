from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERILATOR_FLAGS = "--binary --timing --coverage --assert --trace -Wno-fatal -Wno-lint -Wno-style -j 0"

UVM_SRC = Path(__file__).resolve().parent.parent / "third_party" / "uvm" / "src"
UVM_FLAGS = f"+define+UVM_NO_DPI +incdir+{UVM_SRC} {UVM_SRC}/uvm_pkg.sv"

RUN_SH = """\
#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
rm -rf obj_dir coverage.dat wave.vcd
verilator {flags} --top-module {top} --Mdir obj_dir {extra}{sources} testbench.sv -MAKEFLAGS "OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0" -o simv 2>&1 | tee build.log
./obj_dir/simv +verilator+error+limit+100000 2>&1 | tee sim.log
"""

_ASSERT_FAIL = re.compile(r"ASSERT_FAIL\s+(\w+)|Assertion failed in (?:\w+\.)+(\w+)")
_CHECK_FAIL = re.compile(r"CHECK_FAIL.*")
_BUILD_ERR = re.compile(r"^%Error.*", re.M)
_CODE_KINDS = ("line", "branch", "toggle", "expr")
_STIMULUS_COUNT = re.compile(r"^(?:VECTORS|CYCLES)\s+(\d+)", re.M)
_ASSERT_AT = re.compile(r"^\[(\d+)\].*Assertion failed in (?:\w+\.)+(\w+)", re.M)
_CHECK_AT = re.compile(r"^CHECK_FAIL t=(\d+)\s+(.*)$", re.M)


@dataclass
class SimResult:
    built: bool = False
    passed: bool | None = None
    compile_errors: list[str] = field(default_factory=list)
    check_failures: list[str] = field(default_factory=list)
    assertion_failures: list[str] = field(default_factory=list)
    bins: dict[str, int] = field(default_factory=dict)
    point_pct: dict[str, float] = field(default_factory=dict)
    functional_pct: float | None = None
    stimulus_count: int | None = None
    failures: list[dict] = field(default_factory=list)
    wave: str = ""
    code: dict[str, dict] = field(default_factory=dict)
    log: str = ""
    run_dir: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def verilator_available() -> bool:
    return shutil.which("verilator") is not None


def prepare(run_dir: Path, sources: dict[str, str], testbench: str, top: str = "tb", uvm: bool = False) -> Path:
    """Write sources, testbench.sv and run.sh into run_dir. Returns the script path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, text in sources.items():
        (run_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / name).write_text(text)
    (run_dir / "testbench.sv").write_text(testbench)
    script = run_dir / "run.sh"
    if uvm and not (UVM_SRC / "uvm_pkg.sv").exists():
        raise FileNotFoundError("UVM library missing: run `git submodule update --init`")
    script.write_text(RUN_SH.format(flags=VERILATOR_FLAGS, top=top, sources=" ".join(sources),
                                    extra=UVM_FLAGS + " " if uvm else ""))
    script.chmod(0o755)
    return script


def run(run_dir: Path, dut_hier: str = "tb.dut", timeout: int = 600) -> SimResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["bash", "run.sh"], cwd=run_dir, capture_output=True, text=True, timeout=timeout
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return SimResult(compile_errors=[f"simulation timed out after {timeout}s"], run_dir=str(run_dir))
    result = collect(run_dir, dut_hier)
    if not result.built and not result.compile_errors:
        result.compile_errors = _BUILD_ERR.findall(output) or [output.strip()[-2000:] or "build failed"]
    result.seconds = round(time.monotonic() - start, 2)
    return result


def simulate(run_dir: Path, sources: dict[str, str], testbench: str, dut_hier: str = "tb.dut",
             uvm: bool = False) -> SimResult:
    prepare(run_dir, sources, testbench, uvm=uvm)
    return run(run_dir, dut_hier)


def collect(run_dir: Path, dut_hier: str = "tb.dut") -> SimResult:
    """Read build.log, sim.log and coverage.dat left behind by run.sh."""
    run_dir = Path(run_dir)
    res = SimResult(run_dir=str(run_dir))
    build_log = _read(run_dir / "build.log")
    res.built = (run_dir / "obj_dir" / "simv").exists()
    if not res.built:
        res.compile_errors = _BUILD_ERR.findall(build_log)
        res.log = build_log
        return res

    log = _read(run_dir / "sim.log")
    res.log = log
    res.check_failures = _CHECK_FAIL.findall(log)
    res.assertion_failures = sorted({a or b for a, b in _ASSERT_FAIL.findall(log)})
    res.failures = sorted(
        [{"kind": "assertion", "time": int(t), "label": label, "text": f"assertion {label} failed"}
         for t, label in _ASSERT_AT.findall(log)]
        + [{"kind": "check", "time": int(t), "label": "reference model", "text": text.strip()}
           for t, text in _CHECK_AT.findall(log)],
        key=lambda f: f["time"])[:200]
    if (run_dir / "wave.vcd").exists():
        res.wave = str(run_dir / "wave.vcd")
    counts = _STIMULUS_COUNT.findall(log)
    res.stimulus_count = int(counts[-1]) if counts else None
    if "TEST FAILED" in log or res.assertion_failures or res.check_failures:
        res.passed = False
    elif "TEST PASSED" in log:
        res.passed = True

    records = parse_coverage_dat(run_dir / "coverage.dat")
    res.bins = functional_bins(records)
    res.point_pct, res.functional_pct = functional_summary(res.bins)
    res.code = code_coverage(records, dut_hier)
    return res


def parse_coverage_dat(path: Path) -> list[tuple[dict[str, str], int]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"C '(.*)' (\d+)$", line.strip())
        if m:
            fields = dict(re.findall(r"\x01(\w+)\x02([^\x01]*)", "\x01" + m.group(1)))
            out.append((fields, int(m.group(2))))
    return out


def functional_bins(records) -> dict[str, int]:
    """'coverpoint.bin' -> hit count, from every covergroup in the testbench."""
    bins = {}
    for f, count in records:
        if f.get("page", "").startswith("v_covergroup/"):
            _, _, rest = f.get("h", "").partition(".")
            if rest:
                bins[rest] = count
    return bins


def functional_summary(bins: dict[str, int]) -> tuple[dict[str, float], float | None]:
    """Per-coverpoint % and the overall % as the mean of coverpoints, which is how
    commercial simulators weight get_inst_coverage()."""
    per: dict[str, list[int]] = {}
    for key, count in bins.items():
        cp = key.split(".")[0]
        per.setdefault(cp, []).append(count)
    point_pct = {cp: round(100.0 * sum(c > 0 for c in v) / len(v), 2) for cp, v in per.items()}
    total = round(sum(point_pct.values()) / len(point_pct), 2) if point_pct else None
    return point_pct, total


def code_coverage(records, dut_hier: str) -> dict[str, dict]:
    out = {k: {"hit": 0, "total": 0, "missed": []} for k in _CODE_KINDS}
    for f, count in records:
        kind = f.get("page", "").split("/")[0].removeprefix("v_")
        h = f.get("h", "")
        if kind not in out or not (h == dut_hier or h.startswith(dut_hier + ".")):
            continue
        entry = out[kind]
        entry["total"] += 1
        if count > 0:
            entry["hit"] += 1
        else:
            entry["missed"].append(f"{Path(f.get('f', '')).name}:{f.get('l', '?')} {f.get('o', '')}".strip())
    for entry in out.values():
        entry["pct"] = round(100.0 * entry["hit"] / entry["total"], 2) if entry["total"] else None
    return out


def _read(path: Path) -> str:
    return path.read_text(errors="replace") if path.exists() else ""
