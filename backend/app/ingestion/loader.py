"""Idempotent, versioned loading of validated datasets."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    BenchmarkMonth,
    CurvePoint,
    DatasetVersion,
    Fund,
    FundMonth,
    LiabilityCashflow,
    Scheme,
)
from .adapters import ADAPTERS
from .contracts import CONTRACTS, Issue, ValidationReport


class IngestionError(Exception):
    def __init__(self, report: ValidationReport):
        super().__init__(f"{len(report.errors)} validation error(s)")
        self.report = report


@dataclass
class LoadResult:
    version: DatasetVersion
    duplicate: bool
    report: ValidationReport


def content_hash(df: pd.DataFrame) -> str:
    """Hash of the *normalised data*, not the raw bytes.

    Re-saving a file, reordering rows or changing number formatting produces the
    same hash, so it's recognised as the same dataset; any real value change
    produces a new version.
    """
    data = df.drop(columns=["row_ref"], errors="ignore")
    data = data.sort_values(list(data.columns)).reset_index(drop=True)
    canonical = data.to_csv(index=False, float_format="%.10g")
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_file(
    db: Session,
    scheme: Scheme,
    adapter_name: str,
    filename: str,
    content: bytes,
    actor: str,
) -> LoadResult:
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise ValueError(f"Unknown adapter '{adapter_name}'. Available: {sorted(ADAPTERS)}")

    try:
        df = adapter.parse(content, filename)
    except Exception as exc:  # malformed file
        raise IngestionError(ValidationReport([Issue("error", f"Could not parse file: {exc}")])) from exc

    contract = CONTRACTS[adapter.source]
    report = contract.validate(df)

    fund_ids: dict[str, int] = {}
    if "fund_code" in df.columns:
        funds = {f.code: f.id for f in db.scalars(select(Fund).where(Fund.scheme_id == scheme.id))}
        for idx, code in df["fund_code"].items():
            if isinstance(code, str) and code not in funds:
                report.issues.append(
                    Issue("error", f"Unknown fund code '{code}' for scheme {scheme.code}", df.at[idx, "row_ref"], "fund_code")
                )
        fund_ids = funds

    if not report.ok:
        raise IngestionError(report)

    digest = content_hash(df)
    existing = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.scheme_id == scheme.id,
            DatasetVersion.source == adapter.source,
            DatasetVersion.content_hash == digest,
        )
    )
    if existing is not None:
        return LoadResult(existing, True, report)

    version = DatasetVersion(
        scheme_id=scheme.id,
        source=adapter.source,
        adapter=adapter.name,
        filename=filename,
        content_hash=digest,
        row_count=len(df),
        warnings=[w.to_dict() for w in report.warnings],
        loaded_by=actor,
    )
    db.add(version)
    db.flush()
    _insert_rows(db, scheme, adapter.source, version, df, fund_ids)
    audit(db, actor, "dataset.load", "dataset_version", version.id,
          source=adapter.source, filename=filename, rows=len(df), hash=digest[:12])
    db.flush()
    return LoadResult(version, False, report)


def _insert_rows(db: Session, scheme: Scheme, source: str, version: DatasetVersion,
                 df: pd.DataFrame, fund_ids: dict[str, int]) -> None:
    def num(v):
        return None if pd.isna(v) else float(v)

    rows: list = []
    if source in {"custodian", "manager"}:
        for r in df.itertuples(index=False):
            rows.append(
                FundMonth(
                    dataset_version_id=version.id,
                    fund_id=fund_ids[r.fund_code],
                    source=source,
                    month=r.month,
                    begin_mv=num(getattr(r, "begin_mv", None)),
                    end_mv=num(getattr(r, "end_mv", None)),
                    net_flow=num(getattr(r, "net_flow", None)),
                    reported_return=num(getattr(r, "reported_return", None)),
                    row_ref=r.row_ref,
                )
            )
    elif source == "benchmark":
        for r in df.itertuples(index=False):
            rows.append(BenchmarkMonth(dataset_version_id=version.id, fund_id=fund_ids[r.fund_code],
                                       month=r.month, ret=float(r.ret), row_ref=r.row_ref))
    elif source == "liabilities":
        for r in df.itertuples(index=False):
            rows.append(LiabilityCashflow(dataset_version_id=version.id, scheme_id=scheme.id,
                                          year=int(r.year), amount=float(r.amount), row_ref=r.row_ref))
    elif source == "curve":
        for r in df.itertuples(index=False):
            rows.append(CurvePoint(dataset_version_id=version.id, scheme_id=scheme.id, as_of=r.as_of,
                                   tenor_years=float(r.tenor_years), par_yield=float(r.par_yield),
                                   row_ref=r.row_ref))
    db.add_all(rows)
