"""Ingestion, reconciliation and reporting endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.facts import fmt
from ..audit import audit
from ..auth import get_current_user, require_role
from ..config import settings
from ..db import get_db
from ..ingestion.adapters import ADAPTERS
from ..ingestion.loader import IngestionError, load_file
from ..jobs.queue import enqueue
from ..models import DatasetVersion, LineageFact, ReconBreak, ReconRun, ReportRun, Scheme, User
from ..recon.engine import resolve_break, run_reconciliation
from ..reporting.pipeline import compare_runs, material_blockers, reproduce
from ..reporting.spec import SpecError, list_specs, load_spec
from .deps import get_scheme, resolve_period_end

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# ingestion
@router.get("/adapters", tags=["data"])
def adapters(_: User = Depends(get_current_user)):
    return [{"name": a.name, "source": a.source, "description": a.description} for a in ADAPTERS.values()]


@router.get("/schemes/{scheme_id}/datasets", tags=["data"])
def datasets(scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(DatasetVersion).where(DatasetVersion.scheme_id == scheme.id).order_by(DatasetVersion.id.desc()))
    return [{"id": d.id, "source": d.source, "adapter": d.adapter, "filename": d.filename, "rows": d.row_count,
             "hash": d.content_hash[:12], "warnings": d.warnings, "loaded_by": d.loaded_by, "loaded_at": d.loaded_at}
            for d in rows]


@router.post("/schemes/{scheme_id}/datasets", tags=["data"])
async def upload(adapter: str = Form(...), file: UploadFile = File(...), auto_reconcile: bool = Form(True),
                 scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db),
                 user: User = Depends(require_role("analyst"))):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (20 MB max)")
    if adapter not in ADAPTERS:
        raise HTTPException(400, f"Unknown adapter. Choose from {sorted(ADAPTERS)}")
    filename = (file.filename or "upload").replace("/", "_").replace("\\", "_")[:200]
    try:
        result = load_file(db, scheme, adapter, filename, content, user.email)
    except IngestionError as exc:
        db.rollback()
        raise HTTPException(422, {"message": "File failed validation; nothing was loaded.",
                                  "validation": exc.report.to_dict()}) from exc
    recon = None
    if not result.duplicate and result.version.source in {"custodian", "manager"} and auto_reconcile:
        summary = run_reconciliation(db, scheme, user.email)
        recon = {"run_id": summary.run.id, "breaks": summary.run.n_breaks,
                 "open_material": summary.open_material, "open_minor": summary.open_minor}
    db.commit()
    return {"dataset_version_id": result.version.id, "duplicate": result.duplicate,
            "rows": result.version.row_count, "validation": result.report.to_dict(), "reconciliation": recon}


# reconciliation
def _break_out(b: ReconBreak) -> dict:
    return {"id": b.id, "fund_code": b.fund.code, "fund_name": b.fund.name, "month": b.month,
            "break_type": b.break_type, "severity": b.severity, "status": b.status,
            "custodian_value": b.custodian_value, "manager_value": b.manager_value, "diff_bps": b.diff_bps,
            "resolution": b.resolution, "resolved_value": b.resolved_value, "reason": b.reason,
            "resolved_by": b.resolved_by, "resolved_at": b.resolved_at, "recon_run_id": b.recon_run_id}


@router.post("/schemes/{scheme_id}/recon/run", tags=["reconciliation"])
def recon_run(scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db),
              user: User = Depends(require_role("analyst"))):
    summary = run_reconciliation(db, scheme, user.email)
    db.commit()
    r = summary.run
    return {"run_id": r.id, "compared": r.n_compared, "matched": r.n_matched, "breaks": r.n_breaks,
            "open_material": summary.open_material, "open_minor": summary.open_minor,
            "tolerance_bps": r.tolerance_bps, "material_bps": r.material_bps}


@router.get("/schemes/{scheme_id}/recon/runs", tags=["reconciliation"])
def recon_runs(scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(ReconRun).where(ReconRun.scheme_id == scheme.id).order_by(ReconRun.id.desc()).limit(20))
    return [{"id": r.id, "run_at": r.run_at, "run_by": r.run_by, "compared": r.n_compared, "matched": r.n_matched,
             "breaks": r.n_breaks, "tolerance_bps": r.tolerance_bps, "material_bps": r.material_bps} for r in rows]


@router.get("/schemes/{scheme_id}/recon/breaks", tags=["reconciliation"])
def breaks(status_: str = Query("active", alias="status"), scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db),
           _: User = Depends(get_current_user)):
    q = select(ReconBreak).where(ReconBreak.scheme_id == scheme.id)
    if status_ == "active":
        q = q.where(ReconBreak.status.in_(["open", "resolved"]))
    elif status_ != "all":
        q = q.where(ReconBreak.status == status_)
    return [_break_out(b) for b in db.scalars(q.order_by(ReconBreak.status.desc(), ReconBreak.month.desc()))]


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(custodian|manager|override)$")
    reason: str = Field(min_length=5, max_length=1000)
    override_value: float | None = None


@router.post("/recon/breaks/{break_id}/resolve", tags=["reconciliation"])
def resolve(break_id: int, body: ResolveIn, db: Session = Depends(get_db),
            user: User = Depends(require_role("analyst"))):
    brk = db.get(ReconBreak, break_id)
    if brk is None:
        raise HTTPException(404, "Break not found")
    try:
        resolve_break(db, brk, body.resolution, user.email, body.reason, body.override_value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return _break_out(brk)


# reports
@router.get("/report-specs", tags=["reports"])
def specs(_: User = Depends(get_current_user)):
    return list_specs()


class ReportIn(BaseModel):
    spec: str
    period_end: date | None = None
    override_gate: bool = False


def _run_out(r: ReportRun) -> dict:
    return {"id": r.id, "scheme_id": r.scheme_id, "spec": r.spec_name, "period_end": r.period_end,
            "status": r.status, "fingerprint": r.fingerprint, "commentary_status": r.commentary_status,
            "commentary_provider": r.commentary_provider, "commentary_issues": r.commentary_issues,
            "commentary_text": r.commentary_text, "formats": sorted(r.outputs or {}),
            "gate_overridden": r.gate_overridden, "error": r.error, "job_id": r.job_id,
            "data_versions": r.data_versions, "created_by": r.created_by, "created_at": r.created_at,
            "finished_at": r.finished_at}


@router.post("/schemes/{scheme_id}/reports", status_code=status.HTTP_202_ACCEPTED, tags=["reports"])
def create_report(body: ReportIn, scheme: Scheme = Depends(get_scheme), db: Session = Depends(get_db),
                  user: User = Depends(require_role("analyst"))):
    try:
        load_spec(body.spec)
    except SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    period_end = resolve_period_end(db, scheme, body.period_end)
    blockers = material_blockers(db, scheme.id, period_end)
    if blockers and not body.override_gate:
        raise HTTPException(409, jsonable_encoder({"message": "Report blocked: unresolved material reconciliation breaks.",
                                                   "breaks": [_break_out(b) for b in blockers]}))
    if body.override_gate and user.role != "admin":
        raise HTTPException(403, "Only an admin can override the reconciliation gate")
    run = ReportRun(scheme_id=scheme.id, spec_name=body.spec, period_end=period_end, status="queued",
                    created_by=user.email, gate_overridden=bool(blockers) and body.override_gate)
    db.add(run)
    db.flush()
    job = enqueue(db, "report.generate", {"report_run_id": run.id})
    run.job_id = job.id
    audit(db, user.email, "report.request", "report_run", run.id, spec=body.spec, period_end=str(period_end),
          gate_overridden=run.gate_overridden)
    db.commit()
    return _run_out(run)


@router.get("/reports", tags=["reports"])
def list_reports(scheme_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(ReportRun).order_by(ReportRun.id.desc()).limit(100)
    if scheme_id:
        q = q.where(ReportRun.scheme_id == scheme_id)
    return [_run_out(r) for r in db.scalars(q)]


def _get_run(db: Session, report_id: int) -> ReportRun:
    run = db.get(ReportRun, report_id)
    if run is None:
        raise HTTPException(404, "Report not found")
    return run


@router.get("/reports/compare", tags=["reports"])
def compare(a: int, b: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ra, rb = _get_run(db, a), _get_run(db, b)
    if ra.status != "done" or rb.status != "done":
        raise HTTPException(409, "Both reports must be finished")
    return compare_runs(db, ra, rb)


@router.get("/reports/{report_id}", tags=["reports"])
def get_report(report_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _run_out(_get_run(db, report_id))


@router.get("/reports/{report_id}/download/{fmt_}", tags=["reports"])
def download(report_id: int, fmt_: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    run = _get_run(db, report_id)
    rel = (run.outputs or {}).get(fmt_)
    if not rel:
        raise HTTPException(404, f"No {fmt_} output for this report")
    path = (settings.storage_dir / rel).resolve()
    if settings.storage_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "File missing")
    media = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             "html": "text/html"}[fmt_]
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/reports/{report_id}/facts", tags=["lineage"])
def report_facts(report_id: int, q: str = "", limit: int = 50, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    run = _get_run(db, report_id)
    query = select(LineageFact).where(LineageFact.report_run_id == run.id)
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func, or_
        query = query.where(or_(func.lower(LineageFact.fact_id).like(like), func.lower(LineageFact.label).like(like)))
    rows = db.scalars(query.order_by(LineageFact.id).limit(min(limit, 500)))
    return [{"fact_id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit,
             "display": fmt(f.value, f.unit), "n_inputs": len(f.inputs)} for f in rows]


@router.get("/reports/{report_id}/lineage/{fact_id}", tags=["lineage"])
def report_lineage(report_id: int, fact_id: str, depth: int = 2, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """Lineage as recorded when the report was produced (immutable)."""
    run = _get_run(db, report_id)
    scheme = db.get(Scheme, run.scheme_id)
    facts = {f.fact_id: f for f in db.scalars(select(LineageFact).where(LineageFact.report_run_id == run.id))}
    if fact_id not in facts:
        raise HTTPException(404, "Fact not in this report")

    def node(fid: str, d: int) -> dict:
        f = facts.get(fid)
        if f is None:
            return {"fact_id": fid, "missing": True}
        out = {"fact_id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit,
               "display": fmt(f.value, f.unit, scheme.currency), "formula": f.formula, "sources": f.sources,
               "n_inputs": len(f.inputs)}
        if d > 0:
            out["children"] = [node(i, d - 1) for i in f.inputs[:40]]
        return out

    return node(fact_id, min(depth, 5))


@router.post("/reports/{report_id}/reproduce", tags=["reports"])
def reproduce_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("analyst"))):
    run = _get_run(db, report_id)
    if run.status != "done":
        raise HTTPException(409, "Report is not finished")
    result = reproduce(db, run)
    audit(db, user.email, "report.reproduce", "report_run", run.id, identical=result["identical"],
          changed=result["n_changed_facts"])
    db.commit()
    return result
