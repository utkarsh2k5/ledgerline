"""Read the *current* view of versioned data.

For every (fund, month, source) the row from the most recent dataset version
wins. Older versions stay in the database for audit and reproducibility.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import BenchmarkMonth, CurvePoint, DatasetVersion, Fund, FundMonth, LiabilityCashflow


def funds_frame(db: Session, scheme_id: int) -> pd.DataFrame:
    funds = db.scalars(select(Fund).where(Fund.scheme_id == scheme_id).order_by(Fund.sort_order)).all()
    return pd.DataFrame(
        [
            {
                "fund_id": f.id,
                "fund_code": f.code,
                "fund_name": f.name,
                "asset_class": f.asset_class,
                "manager": f.manager,
                "benchmark_name": f.benchmark_name,
                "target_weight": f.target_weight,
                "effective_duration": f.effective_duration,
                "is_growth": f.is_growth,
                "sort_order": f.sort_order,
            }
            for f in funds
        ]
    )


def latest_fund_months(db: Session, scheme_id: int, source: str) -> pd.DataFrame:
    latest = (
        select(FundMonth.fund_id, FundMonth.month, func.max(FundMonth.dataset_version_id).label("vid"))
        .join(Fund, Fund.id == FundMonth.fund_id)
        .where(Fund.scheme_id == scheme_id, FundMonth.source == source)
        .group_by(FundMonth.fund_id, FundMonth.month)
        .subquery()
    )
    rows = db.execute(
        select(FundMonth, Fund.code)
        .join(Fund, Fund.id == FundMonth.fund_id)
        .join(
            latest,
            (latest.c.fund_id == FundMonth.fund_id)
            & (latest.c.month == FundMonth.month)
            & (latest.c.vid == FundMonth.dataset_version_id),
        )
    ).all()
    cols = ["fund_id", "fund_code", "month", "begin_mv", "end_mv", "net_flow",
            "reported_return", "row_ref", "dataset_version_id"]
    return pd.DataFrame(
        [
            (fm.fund_id, code, fm.month, fm.begin_mv, fm.end_mv, fm.net_flow,
             fm.reported_return, fm.row_ref, fm.dataset_version_id)
            for fm, code in rows
        ],
        columns=cols,
    ).sort_values(["fund_id", "month"]).reset_index(drop=True)


def latest_benchmarks(db: Session, scheme_id: int) -> pd.DataFrame:
    latest = (
        select(BenchmarkMonth.fund_id, BenchmarkMonth.month, func.max(BenchmarkMonth.dataset_version_id).label("vid"))
        .join(Fund, Fund.id == BenchmarkMonth.fund_id)
        .where(Fund.scheme_id == scheme_id)
        .group_by(BenchmarkMonth.fund_id, BenchmarkMonth.month)
        .subquery()
    )
    rows = db.execute(
        select(BenchmarkMonth, Fund.code)
        .join(Fund, Fund.id == BenchmarkMonth.fund_id)
        .join(
            latest,
            (latest.c.fund_id == BenchmarkMonth.fund_id)
            & (latest.c.month == BenchmarkMonth.month)
            & (latest.c.vid == BenchmarkMonth.dataset_version_id),
        )
    ).all()
    return pd.DataFrame(
        [(b.fund_id, code, b.month, b.ret, b.row_ref, b.dataset_version_id) for b, code in rows],
        columns=["fund_id", "fund_code", "month", "bench_ret", "bench_row_ref", "bench_version_id"],
    ).sort_values(["fund_id", "month"]).reset_index(drop=True)


def _latest_version_id(db: Session, scheme_id: int, source: str) -> int | None:
    return db.scalar(
        select(func.max(DatasetVersion.id)).where(
            DatasetVersion.scheme_id == scheme_id, DatasetVersion.source == source
        )
    )


def latest_liabilities(db: Session, scheme_id: int) -> tuple[pd.DataFrame, int | None]:
    vid = _latest_version_id(db, scheme_id, "liabilities")
    if vid is None:
        return pd.DataFrame(columns=["year", "amount", "row_ref"]), None
    rows = db.scalars(
        select(LiabilityCashflow).where(LiabilityCashflow.dataset_version_id == vid).order_by(LiabilityCashflow.year)
    ).all()
    return pd.DataFrame([(r.year, r.amount, r.row_ref) for r in rows], columns=["year", "amount", "row_ref"]), vid


def latest_curve(db: Session, scheme_id: int) -> tuple[pd.DataFrame, int | None]:
    vid = _latest_version_id(db, scheme_id, "curve")
    if vid is None:
        return pd.DataFrame(columns=["as_of", "tenor_years", "par_yield", "row_ref"]), None
    rows = db.scalars(
        select(CurvePoint).where(CurvePoint.dataset_version_id == vid).order_by(CurvePoint.tenor_years)
    ).all()
    return pd.DataFrame(
        [(r.as_of, r.tenor_years, r.par_yield, r.row_ref) for r in rows],
        columns=["as_of", "tenor_years", "par_yield", "row_ref"],
    ), vid


def latest_version_ids(db: Session, scheme_id: int) -> dict[str, int | None]:
    return {
        s: _latest_version_id(db, scheme_id, s)
        for s in ("custodian", "manager", "benchmark", "liabilities", "curve")
    }
