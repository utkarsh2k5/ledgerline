"""Facts: numbers that know where they came from.

Every figure that can appear in a report is a ``Fact`` with a stable id, the
formula that produced it, the ids of the facts it was computed from, and (for
leaf facts) references to the exact source file rows/cells. A report only ever
displays facts, so any number in any output can be traced to its sources.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Iterable

UNITS = {"pct", "bps", "money", "ratio", "years", "count"}


@dataclass
class Fact:
    id: str
    label: str
    value: float
    unit: str
    formula: str
    inputs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"Unknown unit {self.unit!r} for fact {self.id}")
        self.value = float(self.value)

    def to_dict(self) -> dict:
        return asdict(self)


class FactBook:
    def __init__(self, currency: str = "GBP") -> None:
        self.currency = currency
        self._facts: dict[str, Fact] = {}

    def add(self, id: str, label: str, value: float, unit: str, formula: str,
            inputs: Iterable[str] = (), sources: Iterable[str] = ()) -> Fact:
        inputs = list(inputs)
        missing = [i for i in inputs if i not in self._facts]
        if missing:
            raise KeyError(f"Fact {id} depends on unknown facts: {missing[:5]}")
        if id in self._facts:
            raise KeyError(f"Duplicate fact id {id}")
        fact = Fact(id, label, value, unit, formula, inputs, list(sources))
        self._facts[id] = fact
        return fact

    def __contains__(self, id: str) -> bool:
        return id in self._facts

    def __getitem__(self, id: str) -> Fact:
        return self._facts[id]

    def get(self, id: str) -> Fact | None:
        return self._facts.get(id)

    def value(self, id: str) -> float:
        return self._facts[id].value

    def all(self) -> list[Fact]:
        return list(self._facts.values())

    def subset(self, ids: Iterable[str]) -> "FactBook":
        """Facts in ``ids`` plus everything they depend on (transitively)."""
        keep: dict[str, Fact] = {}
        stack = list(ids)
        while stack:
            fid = stack.pop()
            if fid in keep or fid not in self._facts:
                continue
            keep[fid] = self._facts[fid]
            stack.extend(self._facts[fid].inputs)
        book = FactBook(self.currency)
        book._facts = {k: self._facts[k] for k in self._facts if k in keep}  # keep insertion order
        return book

    def trace(self, id: str, max_depth: int = 6, max_children: int = 40) -> dict:
        fact = self._facts[id]
        node = {**fact.to_dict(), "display": fmt(fact.value, fact.unit, self.currency)}
        if max_depth > 0:
            node["children"] = [
                self.trace(i, max_depth - 1, max_children) for i in fact.inputs[:max_children]
            ]
            node["children_truncated"] = max(0, len(fact.inputs) - max_children)
        return node


def fmt(value: float, unit: str, currency: str = "GBP", decimals: int | None = None) -> str:
    """The single place numbers are formatted for display (reports, UI, AI fact sheet)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}.get(currency, currency + " ")
    if unit == "pct":
        d = 2 if decimals is None else decimals
        return f"{value * 100:.{d}f}%"
    if unit == "bps":
        return f"{value:.0f} bps"
    if unit == "money":
        a = abs(value)
        sign = "-" if value < 0 else ""
        if a >= 1e9:
            return f"{sign}{symbol}{a / 1e9:.2f}bn"
        if a >= 1e6:
            return f"{sign}{symbol}{a / 1e6:.1f}m"
        return f"{sign}{symbol}{a:,.0f}"
    if unit == "ratio":
        d = 2 if decimals is None else decimals
        return f"{value:.{d}f}"
    if unit == "years":
        return f"{value:.1f} yrs"
    if unit == "count":
        return f"{value:.0f}"
    raise ValueError(unit)
