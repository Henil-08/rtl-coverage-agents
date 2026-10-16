from __future__ import annotations

from designs.adder4 import DESIGN as ADDER4
from designs.dpram import DESIGN as DPRAM
from designs.base import Design

DESIGNS: dict[str, Design] = {d.name: d for d in (DPRAM, ADDER4)}


def get_design(name: str) -> Design:
    if name not in DESIGNS:
        raise KeyError(f"unknown design {name!r}; choose from {sorted(DESIGNS)}")
    return DESIGNS[name]
