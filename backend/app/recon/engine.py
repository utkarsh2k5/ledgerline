"""Custodian vs fund manager reconciliation.

We compute each month's return from the custodian's valuations (Modified Dietz)
and compare it with what the manager reports.

    diff <= tolerance (5 bps)        matched
    diff <= material (25 bps)        minor   - custodian figure used, report not blocked
    bigger, or one side missing      material - blocks reports until someone resolves it

Resolutions need a reason and are audited. A re-run keeps a resolution unless the
underlying numbers changed (e.g. a corrected file came in), in which case the old
break is marked superseded.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.returns import modified_dietz
from ..audit import audit
from ..config import settings
from ..data_access import latest_fund_months
from ..models import ReconBreak, ReconRun, Scheme, utcnow

_EPS = 1e-12


@dataclass
class ReconSummary:
    run: ReconRun
    open_material: int
    open_minor: int


def compare(custodian: pd.DataFrame, manager: pd.DataFrame, tolerance_bps: float,
            material_bps: float) -> pd.DataFrame:
    """Pure comparison (no DB) so it can be unit/property tested."""
    cust = custodian.copy()
    cust["custodian_value"] = modified_dietz(cust["begin_mv"], cust["end_mv"], cust["net_flow"])
    cust = cust[["fund_id", "month", "custodian_value", "row_ref"]].rename(columns={"row_ref": "custodian_ref"})
    mgr = manager[["fund_id", "month", "reported_return", "row_ref"]].rename(
        columns={"reported_return": "manager_value", "row_ref": "manager_ref"}
    )
    merged = cust.merge(mgr, on=["fund_id", "month"], how="outer")
    diff = (merged["custodian_value"] - merged["manager_value"]) * 10_000
    merged["diff_bps"] = diff
    missing_c = merged["custodian_value"].isna()
    missing_m = merged["manager_value"].isna()
    merged["break_type"] = np.select(
        [missing_c, missing_m, diff.abs() > tolerance_bps + 1e-9],
        ["missing_custodian", "missing_manager", "value_mismatch"],
        default="matched",
    )
    merged["severity"] = np.where(
        (merged["break_type"] != "value_mismatch") | (diff.abs() > material_bps + 1e-9), "material", "minor"
    )
    merged.loc[merged["break_type"] == "matched", "severity"] = "none"
    return merged.sort_values(["fund_id", "month"]).reset_index(drop=True)


def _same(a: float | None, b: float | None) -> bool:
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    if b is None or (isinstance(b, float) and np.isnan(b)):
        return False
    return abs(a - b) < _EPS


def run_reconciliation(db: Session, scheme: Scheme, actor: str,
                       tolerance_bps: float | None = None,
                       material_bps: float | None = None) -> ReconSummary:
    tol = settings.recon_tolerance_bps if tolerance_bps is None else tolerance_bps
    mat = settings.material_break_bps if material_bps is None else material_bps

    custodian = latest_fund_months(db, scheme.id, "custodian")
    manager = latest_fund_months(db, scheme.id, "manager")
    result = compare(custodian, manager, tol, mat)

    run = ReconRun(scheme_id=scheme.id, run_by=actor, tolerance_bps=tol, material_bps=mat,
                   n_compared=len(result), n_matched=int((result["break_type"] == "matched").sum()), n_breaks=0)
    db.add(run)
    db.flush()

    existing = db.scalars(
        select(ReconBreak).where(ReconBreak.scheme_id == scheme.id, ReconBreak.status.in_(["open", "resolved"]))
    ).all()
    by_key = {(b.fund_id, b.month): b for b in existing}

    n_breaks = 0
    seen: set = set()
    for row in result.itertuples(index=False):
        key = (row.fund_id, row.month)
        seen.add(key)
        prior = by_key.get(key)
        cval = None if pd.isna(row.custodian_value) else float(row.custodian_value)
        mval = None if pd.isna(row.manager_value) else float(row.manager_value)
        if row.break_type == "matched":
            if prior is not None:
                prior.status = "superseded"
            continue
        n_breaks += 1
        if prior is not None and _same(prior.custodian_value, cval) and _same(prior.manager_value, mval):
            continue  # unchanged: keep its status (and resolution if any)
        if prior is not None:
            prior.status = "superseded"
        db.add(
            ReconBreak(
                scheme_id=scheme.id,
                recon_run_id=run.id,
                fund_id=row.fund_id,
                month=row.month,
                break_type=row.break_type,
                custodian_value=cval,
                manager_value=mval,
                diff_bps=None if pd.isna(row.diff_bps) else float(row.diff_bps),
                severity=row.severity,
                status="open",
            )
        )
    for key, prior in by_key.items():
        if key not in seen:
            prior.status = "superseded"

    run.n_breaks = n_breaks
    audit(db, actor, "recon.run", "recon_run", run.id, compared=run.n_compared, breaks=n_breaks,
          tolerance_bps=tol, material_bps=mat)
    db.flush()
    open_breaks = db.scalars(
        select(ReconBreak).where(ReconBreak.scheme_id == scheme.id, ReconBreak.status == "open")
    ).all()
    return ReconSummary(
        run=run,
        open_material=sum(b.severity == "material" for b in open_breaks),
        open_minor=sum(b.severity == "minor" for b in open_breaks),
    )


def resolve_break(db: Session, brk: ReconBreak, resolution: str, actor: str, reason: str,
                  override_value: float | None = None) -> ReconBreak:
    if brk.status != "open":
        raise ValueError(f"Break {brk.id} is {brk.status}, not open")
    if not reason or len(reason.strip()) < 5:
        raise ValueError("A reason of at least 5 characters is required")
    if resolution == "custodian":
        if brk.custodian_value is None:
            raise ValueError("No custodian value to accept")
        value = brk.custodian_value
    elif resolution == "manager":
        if brk.manager_value is None:
            raise ValueError("No manager value to accept")
        value = brk.manager_value
    elif resolution == "override":
        if override_value is None:
            raise ValueError("Override requires a value")
        value = float(override_value)
        if abs(value) > 0.5:
            raise ValueError("Override value looks like a percentage; send a decimal (0.0123 for 1.23%)")
    else:
        raise ValueError("resolution must be custodian, manager or override")

    brk.status = "resolved"
    brk.resolution = resolution
    brk.resolved_value = value
    brk.reason = reason.strip()
    brk.resolved_by = actor
    brk.resolved_at = utcnow()
    audit(db, actor, "recon.resolve", "recon_break", brk.id, resolution=resolution, value=value,
          reason=brk.reason, custodian=brk.custodian_value, manager=brk.manager_value)
    db.flush()
    return brk


def golden_returns(db: Session, scheme: Scheme) -> pd.DataFrame:
    """The returns analytics should use, with provenance for each cell.

    Columns: fund_id, month, begin_mv, end_mv, net_flow, ret, origin, row_refs, break_id
    """
    custodian = latest_fund_months(db, scheme.id, "custodian")
    manager = latest_fund_months(db, scheme.id, "manager")
    custodian = custodian.assign(cust_ret=modified_dietz(custodian["begin_mv"], custodian["end_mv"], custodian["net_flow"]))
    merged = custodian[["fund_id", "month", "begin_mv", "end_mv", "net_flow", "cust_ret", "row_ref"]].merge(
        manager[["fund_id", "month", "reported_return", "row_ref"]].rename(columns={"row_ref": "mgr_ref"}),
        on=["fund_id", "month"], how="outer",
    )
    breaks = {
        (b.fund_id, b.month): b
        for b in db.scalars(
            select(ReconBreak).where(ReconBreak.scheme_id == scheme.id, ReconBreak.status.in_(["open", "resolved"]))
        )
    }
    out = []
    for r in merged.itertuples(index=False):
        b = breaks.get((r.fund_id, r.month))
        refs = [x for x in (r.row_ref, r.mgr_ref) if isinstance(x, str)]
        if b is not None and b.status == "resolved":
            ret, origin = b.resolved_value, b.resolution
            refs = refs + [f"recon_break#{b.id} ({b.resolution} by {b.resolved_by}: {b.reason})"]
        elif not pd.isna(r.cust_ret):
            ret, origin = r.cust_ret, "custodian"
            if b is not None:
                refs = refs + [f"recon_break#{b.id} (open, {b.severity})"]
        else:
            ret, origin = np.nan, "unresolved"
        out.append({
            "fund_id": r.fund_id, "month": r.month, "begin_mv": r.begin_mv, "end_mv": r.end_mv,
            "net_flow": r.net_flow, "ret": ret, "origin": origin, "row_refs": refs,
            "break_id": b.id if b is not None else None,
            "break_open": bool(b is not None and b.status == "open"),
            "break_severity": b.severity if b is not None else None,
        })
    return pd.DataFrame(out).sort_values(["fund_id", "month"]).reset_index(drop=True)


def open_breaks(db: Session, scheme_id: int, severity: str | None = None) -> list[ReconBreak]:
    q = select(ReconBreak).where(ReconBreak.scheme_id == scheme_id, ReconBreak.status == "open")
    if severity:
        q = q.where(ReconBreak.severity == severity)
    return list(db.scalars(q.order_by(ReconBreak.month, ReconBreak.fund_id)))
