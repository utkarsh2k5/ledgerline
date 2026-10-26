from __future__ import annotations

from datetime import date

from fastapi import Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FundMonth, Fund, Scheme


def get_scheme(scheme_id: int, db: Session = Depends(get_db)) -> Scheme:
    scheme = db.get(Scheme, scheme_id)
    if scheme is None:
        raise HTTPException(404, "Scheme not found")
    return scheme


def latest_month(db: Session, scheme_id: int) -> date | None:
    return db.scalar(
        select(func.max(FundMonth.month)).join(Fund, Fund.id == FundMonth.fund_id)
        .where(Fund.scheme_id == scheme_id, FundMonth.source == "custodian")
    )


def resolve_period_end(db: Session, scheme: Scheme, period_end: date | None) -> date:
    if period_end is not None:
        return period_end
    latest = latest_month(db, scheme.id)
    if latest is None:
        raise HTTPException(409, "No custodian data loaded for this scheme yet")
    return latest
