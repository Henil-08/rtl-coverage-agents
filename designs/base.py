from __future__ import annotations

import random
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_FORBIDDEN = re.compile(r"\$finish|\$stop|\bmodule\b|\binitial\b|\balways\w*\b|\bforce\b|#\s*\d")
_ASSERT_LABEL = re.compile(r"^\s*(\w+)\s*:\s*assert\b")


@dataclass(frozen=True)
class Mutant:
    id: str
    category: str
    description: str
    find: str
    replace: str
    file: str = ""

    def apply(self, golden: str) -> str:
        if golden.count(self.find) != 1:
            raise ValueError(f"{self.id}: mutation anchor must appear exactly once")
        return f"// MUTANT {self.id} [{self.category}]: {self.description}\n" + golden.replace(self.find, self.replace)


@dataclass
class Design:
    name: str
    title: str
    root: Path
    rtl_files: tuple[str, ...]
    drivers: tuple[str, ...]
    harness_doc: str
    signals: str
    mutants: list[Mutant]
    default_plan: list[dict]
    default_assertions: str
    fallback: Callable[..., tuple[str, str]]
    random_stimulus: Callable[[random.Random, int], str]
    dut_hier: str = "tb.dut"
    extra: dict = field(default_factory=dict)

    def sources(self) -> dict[str, str]:
        return {f: (self.root / f).read_text() for f in self.rtl_files}

    def spec(self) -> str:
        return (self.root / "spec.md").read_text()

    def template(self) -> str:
        return (self.root / "harness.sv").read_text()

    def covergroup(self) -> str:
        m = re.search(r"^\s*covergroup\b.*?^\s*endgroup", self.template(), re.S | re.M)
        return m.group(0) if m else ""

    def mutant_sources(self, mutant: Mutant) -> dict[str, str]:
        srcs = self.sources()
        target = mutant.file or self.rtl_files[0]
        srcs[target] = mutant.apply(srcs[target])
        return srcs

    def build_testbench(self, blocks: list[dict], assertions: list[dict]) -> str:
        tasks, calls = [], []
        for blk in blocks:
            it = blk["iteration"]
            tasks.append(
                f"  // iteration {it}: {blk.get('focus', '').strip()}\n"
                f"  task automatic stim_it{it}();\n{indent(blk['stimulus'], 4)}\n  endtask"
            )
            calls.append(f"    stim_it{it}();")
        active = [a["code"] for a in assertions if a.get("status", "active") == "active"]
        out = self.template()
        out = out.replace("  // @ASSERTIONS", indent("\n".join(active), 2) if active else "  // no assertions")
        out = out.replace("  // @STIMULUS_TASKS", "\n\n".join(tasks) or "  // no stimulus yet")
        out = out.replace("    // @STIMULUS_CALLS", "\n".join(calls) or "    // no stimulus yet")
        return out


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    body = textwrap.dedent(text.strip("\n").expandtabs(4))
    return "\n".join(pad + line.rstrip() if line.strip() else "" for line in body.splitlines())


def strip_fences(text: str) -> str:
    return re.sub(r"```\w*", "", text).strip()


def valid_stimulus(text: str, drivers: tuple[str, ...]) -> bool:
    calls = any(re.search(rf"\b{d}\s*\(", text) for d in drivers)
    return calls and not _FORBIDDEN.search(text)


def split_assertions(text: str) -> list[dict]:
    """One dict per `label: assert property ...;` statement. Statements may span lines."""
    out, current = [], []
    for line in strip_fences(text).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if _ASSERT_LABEL.match(line):
            if current:
                out.append(" ".join(current))
            current = [line]
        elif current and not re.search(r"(;|\bend)$", current[-1]):
            current.append(line)
    if current:
        out.append(" ".join(current))
    result = []
    for stmt in out:
        m = _ASSERT_LABEL.match(stmt)
        if not m or "assert property" not in stmt or _FORBIDDEN.search(stmt):
            continue
        label = m.group(1)
        if not re.search(r"\belse\b", stmt):
            stmt = stmt.rstrip().rstrip(";") + f' else begin $error("ASSERT_FAIL {label}"); errors++; end'
        result.append({"label": label, "code": stmt, "status": "active"})
    return result


def dedupe_labels(new: list[dict], existing: list[dict]) -> list[dict]:
    taken = {a["label"] for a in existing}
    for a in new:
        label = a["label"]
        n = 2
        while label in taken:
            label = f"{a['label']}_{n}"
            n += 1
        if label != a["label"]:
            a["code"] = re.sub(rf"\b{re.escape(a['label'])}\b", label, a["code"])
            a["label"] = label
        taken.add(label)
    return new
