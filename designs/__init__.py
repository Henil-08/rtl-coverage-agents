from __future__ import annotations

from designs import user
from designs.adder4 import DESIGN as ADDER4
from designs.base import Design
from designs.dpram import DESIGN as DPRAM

DESIGNS: dict[str, Design] = {d.name: d for d in (DPRAM, ADDER4)}


def get_design(name: str) -> Design:
    if name in DESIGNS:
        return DESIGNS[name]
    if name in user.names():
        return user.load(name)
    raise KeyError(f"unknown design {name!r}; choose from {sorted(all_designs())}")


def all_designs() -> dict[str, Design]:
    return {**DESIGNS, **{n: user.load(n) for n in user.names()}}
