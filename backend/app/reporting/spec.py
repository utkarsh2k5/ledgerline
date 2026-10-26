"""Report-as-code: report layouts are declarative YAML specs, validated on load.

A new client layout is a new YAML file, not new code. See ``report_specs/``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from ..config import BACKEND_DIR

SPEC_DIR = BACKEND_DIR / "report_specs"
PERIOD = Literal["3m", "ytd", "1y", "3y"]


class KPIItem(BaseModel):
    fact: str
    label: str | None = None
    sub: str | None = None  # optional fact id shown underneath


class SectionSpec(BaseModel):
    type: Literal["kpis", "commentary", "performance_table", "chart", "allocation", "attribution",
                  "risk", "funding", "data_quality", "lineage_appendix"]
    title: str | None = None
    items: list[KPIItem] = Field(default_factory=list)          # kpis
    periods: list[PERIOD] = Field(default_factory=lambda: ["3m", "1y", "3y"])  # performance_table
    period: PERIOD = "1y"                                          # attribution
    chart: Literal["cumulative", "allocation"] | None = None      # chart
    include_simulation: bool = True                                # funding
    words: int = 160                                               # commentary target length

    @model_validator(mode="after")
    def _check(self) -> "SectionSpec":
        if self.type == "kpis" and not self.items:
            raise ValueError("kpis section needs at least one item")
        if self.type == "chart" and self.chart is None:
            raise ValueError("chart section needs 'chart'")
        return self


class ReportSpec(BaseModel):
    name: str
    title: str
    description: str = ""
    audience: str = "Trustees"
    formats: list[Literal["docx", "pptx", "html"]] = Field(default_factory=lambda: ["docx", "pptx", "html"])
    linking: Literal["carino", "grap"] = "carino"
    sections: list[SectionSpec]


class SpecError(Exception):
    pass


def load_spec(name: str) -> ReportSpec:
    path = SPEC_DIR / f"{name}.yaml"
    if not path.exists() or not name.replace("_", "").replace("-", "").isalnum():
        raise SpecError(f"Unknown report spec '{name}'")
    return parse_spec(path.read_text(encoding="utf-8"))


def parse_spec(text: str) -> ReportSpec:
    try:
        return ReportSpec.model_validate(yaml.safe_load(text))
    except (ValidationError, yaml.YAMLError) as exc:
        raise SpecError(str(exc)) from exc


def list_specs() -> list[dict]:
    out = []
    for path in sorted(SPEC_DIR.glob("*.yaml")):
        spec = parse_spec(path.read_text(encoding="utf-8"))
        out.append({"name": spec.name, "title": spec.title, "description": spec.description,
                    "audience": spec.audience, "formats": spec.formats,
                    "sections": [s.type for s in spec.sections], "yaml": path.read_text(encoding="utf-8")})
    return out


def spec_path(name: str) -> Path:
    return SPEC_DIR / f"{name}.yaml"
