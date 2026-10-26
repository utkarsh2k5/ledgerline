"""Intermediate representation (IR) of a report.

The builder turns (spec + facts) into this format-neutral document; each
renderer (Word, PowerPoint, HTML) turns the IR into a file. Adding a new
output format = one new renderer, nothing else changes. The IR is also what
gets fingerprinted, so "is this the same report?" is answered on content,
not on file bytes (Office files embed timestamps).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Literal, Union

Tone = Literal["neutral", "good", "bad", "warn"]


@dataclass
class Cell:
    text: str
    fact_id: str | None = None
    tone: Tone = "neutral"
    bold: bool = False
    align: Literal["left", "right"] = "right"


@dataclass
class Heading:
    text: str
    level: int = 1
    kind: str = "heading"


@dataclass
class Paragraph:
    text: str
    style: Literal["body", "note", "lead"] = "body"
    kind: str = "paragraph"


@dataclass
class KPI:
    label: str
    display: str
    fact_id: str
    sub: str | None = None
    tone: Tone = "neutral"
    sub_fact_id: str | None = None


@dataclass
class KPIGrid:
    items: list[KPI]
    kind: str = "kpis"


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Cell]]
    caption: str | None = None
    note: str | None = None
    kind: str = "table"


@dataclass
class Chart:
    chart: str
    title: str
    data: dict
    caption: str | None = None
    image: str | None = None  # filled in by the renderer pipeline; excluded from fingerprint
    kind: str = "chart"


@dataclass
class Commentary:
    text: str
    status: Literal["verified", "fallback", "unverified"]
    provider: str
    issues: list[dict] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    kind: str = "commentary"


@dataclass
class Callout:
    text: str
    tone: Tone = "warn"
    kind: str = "callout"


@dataclass
class Section:
    title: str
    blocks: list["Block"]
    slide_title: str | None = None
    kind: str = "section"


Block = Union[Heading, Paragraph, KPIGrid, Table, Chart, Commentary, Callout]


@dataclass
class Document:
    title: str
    subtitle: str
    scheme_name: str
    period_label: str
    prepared_for: str
    sections: list[Section]
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def fact_ids(self) -> list[str]:
        ids: list[str] = []
        for s in self.sections:
            for b in s.blocks:
                if isinstance(b, KPIGrid):
                    ids += [k.fact_id for k in b.items] + [k.sub_fact_id for k in b.items if k.sub_fact_id]
                elif isinstance(b, Table):
                    ids += [c.fact_id for row in b.rows for c in row if c.fact_id]
                elif isinstance(b, Commentary):
                    ids += b.fact_ids
        return list(dict.fromkeys(ids))


def fingerprint(doc: Document, fact_values: dict[str, float]) -> str:
    """Content hash of the report: structure, text and every number displayed."""
    payload = doc.to_dict()
    payload.pop("meta", None)
    for s in payload["sections"]:
        for b in s["blocks"]:
            b.pop("image", None)
    payload["facts"] = {k: round(v, 10) for k, v in sorted(fact_values.items())}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def diff_facts(old: dict[str, float], new: dict[str, float], tol: float = 1e-10) -> list[dict]:
    """Which numbers changed between two report runs."""
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if a is None or b is None or abs(a - b) > tol:
            out.append({"fact_id": k, "before": a, "after": b,
                        "change": None if a is None or b is None else b - a})
    return out
