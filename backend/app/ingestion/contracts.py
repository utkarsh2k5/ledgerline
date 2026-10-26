"""Data contracts: what a normalised dataset must look like before we trust it.

Each adapter turns a messy source file into a tidy DataFrame; the contract then
checks types, nulls, ranges and uniqueness and returns a report with row-level
issues. Errors block the load. Warnings are stored with the dataset version so
a reviewer can see them later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

Severity = Literal["error", "warning"]


@dataclass
class Issue:
    severity: Severity
    message: str
    row_ref: str | None = None
    column: str | None = None

    def to_dict(self) -> dict:
        return {"severity": self.severity, "message": self.message, "row_ref": self.row_ref, "column": self.column}


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
        }


@dataclass(frozen=True)
class Column:
    name: str
    kind: Literal["str", "float", "date", "int"]
    required: bool = True
    # (predicate over the numeric series, message, severity)
    checks: tuple[tuple[Callable[[pd.Series], pd.Series], str, Severity], ...] = ()


@dataclass(frozen=True)
class Contract:
    name: str
    columns: tuple[Column, ...]
    unique_key: tuple[str, ...] = ()

    def validate(self, df: pd.DataFrame) -> ValidationReport:
        report = ValidationReport()
        refs = df["row_ref"] if "row_ref" in df.columns else pd.Series([None] * len(df), index=df.index)

        missing_cols = [c.name for c in self.columns if c.name not in df.columns]
        for col in missing_cols:
            report.issues.append(Issue("error", f"Missing required column '{col}'", column=col))
        if missing_cols:
            return report
        if df.empty:
            report.issues.append(Issue("error", "File contains no data rows"))
            return report

        for col in self.columns:
            series = df[col.name]
            nulls = series.isna()
            if col.required:
                for idx in series[nulls].index:
                    report.issues.append(Issue("error", f"'{col.name}' is empty", refs[idx], col.name))
            if col.kind in {"float", "int"}:
                numeric = pd.to_numeric(series, errors="coerce")
                bad = numeric.isna() & ~nulls
                for idx in series[bad].index:
                    report.issues.append(
                        Issue("error", f"'{col.name}' is not a number: {series[idx]!r}", refs[idx], col.name)
                    )
                valid = numeric.dropna()
                for predicate, message, severity in col.checks:
                    failing = valid[~predicate(valid)]
                    for idx in failing.index:
                        report.issues.append(
                            Issue(severity, f"'{col.name}' {message} (got {valid[idx]:,.6g})", refs[idx], col.name)
                        )
            if col.kind == "date":
                parsed = series.map(lambda v: v if hasattr(v, "year") else pd.NaT)
                for idx in series[parsed.isna() & ~nulls].index:
                    report.issues.append(Issue("error", f"'{col.name}' is not a date: {series[idx]!r}", refs[idx], col.name))

        if self.unique_key:
            dupes = df[df.duplicated(list(self.unique_key), keep=False)]
            for idx in dupes.index:
                key = ", ".join(f"{k}={df.at[idx, k]}" for k in self.unique_key)
                report.issues.append(Issue("error", f"Duplicate row for {key}", refs[idx]))
        return report


def _ge(x: float):
    return lambda s: s >= x


def _between(lo: float, hi: float):
    return lambda s: (s >= lo) & (s <= hi)


CUSTODIAN = Contract(
    "custodian_valuations",
    (
        Column("fund_code", "str"),
        Column("month", "date"),
        Column("begin_mv", "float", checks=((_ge(0), "must be non-negative", "error"),)),
        Column("end_mv", "float", checks=((_ge(0), "must be non-negative", "error"),)),
        Column("net_flow", "float"),
    ),
    unique_key=("fund_code", "month"),
)

MANAGER = Contract(
    "manager_returns",
    (
        Column("fund_code", "str"),
        Column("month", "date"),
        Column(
            "reported_return",
            "float",
            required=False,  # a blank cell = manager did not report (recon will flag it)
            checks=((_between(-0.25, 0.25), "is an implausible monthly return (|r| > 25%)", "warning"),),
        ),
    ),
    unique_key=("fund_code", "month"),
)

BENCHMARK = Contract(
    "benchmark_returns",
    (
        Column("fund_code", "str"),
        Column("month", "date"),
        Column(
            "ret",
            "float",
            checks=((_between(-0.25, 0.25), "is an implausible monthly return (|r| > 25%)", "warning"),),
        ),
    ),
    unique_key=("fund_code", "month"),
)

LIABILITIES = Contract(
    "liability_cashflows",
    (
        Column("year", "int", checks=((_ge(1), "must be >= 1", "error"),)),
        Column("amount", "float", checks=((_ge(0), "must be non-negative", "error"),)),
    ),
    unique_key=("year",),
)

CURVE = Contract(
    "yield_curve",
    (
        Column("as_of", "date"),
        Column("tenor_years", "float", checks=((_between(0.01, 100), "must be between 0.01 and 100 years", "error"),)),
        Column("par_yield", "float", checks=((_between(-0.05, 0.25), "is outside -5%..25%", "error"),)),
    ),
    unique_key=("as_of", "tenor_years"),
)

CONTRACTS = {
    "custodian": CUSTODIAN,
    "manager": MANAGER,
    "benchmark": BENCHMARK,
    "liabilities": LIABILITIES,
    "curve": CURVE,
}
