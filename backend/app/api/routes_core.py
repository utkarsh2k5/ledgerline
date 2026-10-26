"""Auth, schemes, analytics, funding and lineage endpoints."""
from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.attribution import multi_period_attribution
from ..analytics.cache import get_analysis
from ..analytics.engine import PERIOD_LABELS, AnalyticsError
from ..analytics.facts import fmt
from ..config import settings
from ..auth import create_token, get_current_user, verify_password
from ..data_access import funds_frame, latest_curve, latest_liabilities
from ..db import get_db
from ..funding.curve import bootstrap
from ..funding.liabilities import stress_test
from ..models import AuditLog, Job, Scheme, User
from .deps import get_scheme, resolve_period_end

router = APIRouter()


# auth
class LoginIn(BaseModel):
    email: str
    password: str


def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


@router.post("/auth/login", tags=["auth"])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_token(user), "token_type": "bearer", "user": _user_out(user)}


class DemoIn(BaseModel):
    role: Literal["analyst", "admin", "viewer"]


@router.get("/auth/demo", tags=["auth"])
def demo_info():
    return {"enabled": settings.demo_mode}


@router.post("/auth/demo", tags=["auth"])
def demo_login(body: DemoIn, db: Session = Depends(get_db)):
    """Sign in as one of the seeded demo users by role, no password needed."""
    if not settings.demo_mode:
        raise HTTPException(404, "Demo access is turned off")
    user = db.scalar(select(User).where(User.role == body.role).order_by(User.id))
    if user is None:
        raise HTTPException(404, f"No {body.role} user exists; run the seed")
    return {"access_token": create_token(user), "token_type": "bearer", "user": _user_out(user)}


@router.get("/auth/me", tags=["auth"])
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


# helpers
def _analysis(db: Session, scheme: Scheme, period_end: date | None):
    pe = resolve_period_end(db, scheme, period_end)
    try:
        return get_analysis(db, scheme, pe)
    except AnalyticsError as exc:
        raise HTTPException(409, str(exc)) from exc


def _f(book, fid: str) -> dict | None:
    f = book.get(fid)
    if f is None:
        return None
    v = None if f.value is None or (isinstance(f.value, float) and np.isnan(f.value)) else f.value
    return {"id": f.id, "label": f.label, "value": v, "unit": f.unit, "display": fmt(f.value, f.unit, book.currency)}


# schemes & analytics
@router.get("/schemes", tags=["schemes"])
def list_schemes(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from .deps import latest_month

    out = []
    for s in db.scalars(select(Scheme).order_by(Scheme.id)):
        out.append({"id": s.id, "code": s.code, "name": s.name, "currency": s.currency, "sponsor": s.sponsor,
                    "latest_month": latest_month(db, s.id),
                    "funds": funds_frame(db, s.id).to_dict(orient="records")})
    return out


@router.get("/schemes/{scheme_id}/overview", tags=["analytics"])
def overview(period_end: date | None = None, scheme: Scheme = Depends(get_scheme),
             db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    b = a.facts
    kpis = [_f(b, i) for i in ("mv.TOTAL.end", "perf.TOTAL.3m.ret", "perf.TOTAL.3m.excess", "perf.TOTAL.1y.ret",
                               "perf.TOTAL.1y.excess", "funding.ratio", "funding.surplus", "funding.hedge_ratio")]
    rows = []
    for r in [*a.funds.to_dict(orient="records"), {"fund_code": "TOTAL", "fund_name": "Total fund", "manager": "",
                                                   "asset_class": "", "target_weight": 1.0}]:
        code = r["fund_code"]
        rows.append({
            "code": code, "name": r["fund_name"], "manager": r.get("manager", ""), "asset_class": r.get("asset_class", ""),
            "value": _f(b, f"mv.{code}.end"),
            "allocation": _f(b, f"alloc.{code}.actual"), "target": _f(b, f"wb.{code}"),
            "periods": {p: {"ret": _f(b, f"perf.{code}.{p}.ret"), "bench": _f(b, f"perf.{code}.{p}.bench"),
                            "excess": _f(b, f"perf.{code}.{p}.excess")} for p in a.periods},
        })
    return {
        "scheme": {"id": scheme.id, "code": scheme.code, "name": scheme.name, "currency": scheme.currency},
        "period_end": a.period_end,
        "periods": [{"key": p, "label": PERIOD_LABELS[p], "months": n} for p, n in a.periods.items()],
        "kpis": [k for k in kpis if k],
        "funds": rows,
        "cumulative": {"months": [m.isoformat() for m in a.cumulative["month"]],
                       "portfolio": a.cumulative["portfolio"].tolist(), "benchmark": a.cumulative["benchmark"].tolist()},
        "recon": {"open_material": int(b.value("recon.open_material")), "open_minor": int(b.value("recon.open_minor"))},
        "available_months": [m.isoformat() for m in a.months],
    }


@router.get("/schemes/{scheme_id}/attribution", tags=["analytics"])
def attribution(period: str = "1y", period_end: date | None = None, scheme: Scheme = Depends(get_scheme),
                db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    if period not in a.periods:
        raise HTTPException(400, f"Period {period} not available; choose from {list(a.periods)}")
    months = a.months[-a.periods[period]:]
    frame = a.attribution_input[a.attribution_input["month"].isin(months)]
    names = dict(zip(a.funds["fund_code"], a.funds["fund_name"]))
    methods = {}
    for m in ("carino", "grap", "sum"):
        res = multi_period_attribution(frame, m)
        methods[m] = {
            "segments": [{"code": c, "name": names[c], **{k: float(v) for k, v in res.segments.loc[c].items()}}
                         for c in res.segments.index],
            "totals": res.totals(),
            "explained": float(res.segments["total"].sum()),
            "residual": float(res.excess_return - res.segments["total"].sum()),
        }
        if m == "carino":
            monthly = res.monthly.groupby(["month", "effect"])["raw"].sum().unstack()
            methods[m]["monthly"] = [{"month": k.isoformat(), **{e: float(v) for e, v in row.items()}}
                                     for k, row in monthly.iterrows()]
            portfolio, benchmark = res.portfolio_return, res.benchmark_return
    return {"period": period, "label": PERIOD_LABELS[period], "portfolio_return": portfolio,
            "benchmark_return": benchmark, "excess_return": portfolio - benchmark, "methods": methods}


@router.get("/schemes/{scheme_id}/risk", tags=["analytics"])
def risk(period_end: date | None = None, scheme: Scheme = Depends(get_scheme),
         db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    p = "3y" if "3y" in a.periods else "1y"
    rows = []
    for code, name in [*zip(a.funds["fund_code"], a.funds["fund_name"]), ("TOTAL", "Total fund")]:
        rows.append({"code": code, "name": name,
                     **{m: _f(a.facts, f"risk.{code}.{p}.{m}") for m in ("vol", "te", "ir", "sharpe", "maxdd")}})
    return {"period": p, "rows": rows}


@router.get("/schemes/{scheme_id}/funding", tags=["funding"])
def funding(period_end: date | None = None, scheme: Scheme = Depends(get_scheme),
            db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    if a.funding is None:
        raise HTTPException(409, "Load liability cashflows and a yield curve to see the funding position")
    b = a.facts
    return {
        "kpis": [_f(b, i) for i in ("funding.ratio", "funding.assets", "funding.liabilities", "funding.surplus",
                                     "funding.hedge_ratio", "funding.liab_duration", "funding.liab_pv01",
                                     "funding.asset_pv01")],
        "stress": a.funding["stress"],
        "simulation": a.funding["simulation"],
        "curve": a.funding["curve"],
        "cashflows": a.funding["cashflows"],
    }


class StressIn(BaseModel):
    rates_bps: int = Field(0, ge=-400, le=400)
    equity: float = Field(0.0, ge=-0.8, le=0.8)


@router.post("/schemes/{scheme_id}/funding/stress", tags=["funding"])
def custom_stress(body: StressIn, period_end: date | None = None, scheme: Scheme = Depends(get_scheme),
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    liabs, _v = latest_liabilities(db, scheme.id)
    curve_df, _c = latest_curve(db, scheme.id)
    if liabs.empty or curve_df.empty:
        raise HTTPException(409, "No liability / curve data")
    curve = bootstrap(curve_df["tenor_years"], curve_df["par_yield"], max_year=max(80, int(liabs["year"].max())))
    cf = np.zeros(int(liabs["year"].max()))
    cf[liabs["year"].to_numpy() - 1] = liabs["amount"].to_numpy()
    meta = a.funds.set_index("fund_code")
    values = np.array([a.facts.value(f"mv.{c}.end") for c in meta.index])
    res = stress_test(values, meta["effective_duration"].to_numpy(), meta["is_growth"].to_numpy(), cf, curve,
                      {"Custom": {"rates_bps": body.rates_bps, "equity": body.equity}})
    return res[0]


@router.get("/schemes/{scheme_id}/facts/{fact_id}/trace", tags=["lineage"])
def live_trace(fact_id: str, period_end: date | None = None, depth: int = 3, scheme: Scheme = Depends(get_scheme),
               db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = _analysis(db, scheme, period_end)
    if fact_id not in a.facts:
        raise HTTPException(404, f"Unknown fact {fact_id}")
    return a.facts.trace(fact_id, max_depth=min(depth, 6))


# jobs & audit
@router.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"id": job.id, "kind": job.kind, "status": job.status, "attempts": job.attempts,
            "error": job.error, "result": job.result, "created_at": job.created_at, "finished_at": job.finished_at}


@router.get("/audit", tags=["audit"])
def audit_log(limit: int = 100, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    return [{"id": r.id, "at": r.at, "actor": r.actor, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "details": r.details} for r in rows]
