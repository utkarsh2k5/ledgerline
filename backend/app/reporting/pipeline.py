"""End-to-end report generation: gate -> analytics -> commentary -> IR -> files -> lineage."""
from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.commentary import _check, fact_sheet, generate_commentary
from ..analytics.engine import Analysis, build_analysis
from ..audit import audit
from ..config import settings
from ..models import LineageFact, ReconBreak, ReportRun, Scheme, utcnow
from . import charts
from .builder import build_document
from .ir import Chart, Commentary, Document, diff_facts, fingerprint
from .renderers.docx_renderer import render_docx
from .renderers.html_renderer import render_html
from .renderers.pptx_renderer import render_pptx
from .spec import ReportSpec, load_spec


class GateError(Exception):
    """Report blocked: unresolved material reconciliation breaks."""


def run_dir(run_id: int) -> Path:
    return settings.storage_dir / "reports" / str(run_id)


def material_blockers(db: Session, scheme_id: int, period_end) -> list[ReconBreak]:
    return list(db.scalars(
        select(ReconBreak).where(ReconBreak.scheme_id == scheme_id, ReconBreak.status == "open",
                                 ReconBreak.severity == "material", ReconBreak.month <= period_end)
        .order_by(ReconBreak.month)
    ))


def _breaks_for_report(db: Session, scheme_id: int, period_end) -> list[dict]:
    rows = db.scalars(
        select(ReconBreak).where(ReconBreak.scheme_id == scheme_id, ReconBreak.status.in_(["open", "resolved"]),
                                 ReconBreak.month <= period_end).order_by(ReconBreak.month, ReconBreak.fund_id)
    ).all()
    return [{"id": b.id, "fund_code": b.fund.code, "month": b.month.isoformat(), "break_type": b.break_type,
             "severity": b.severity, "status": b.status, "resolution": b.resolution,
             "custodian_value": b.custodian_value, "manager_value": b.manager_value, "reason": b.reason}
            for b in rows]


def _wants_simulation(spec: ReportSpec) -> bool:
    return any(s.type == "funding" and s.include_simulation for s in spec.sections)


def _attr_periods(spec: ReportSpec) -> tuple[str, ...]:
    ps = {s.period for s in spec.sections if s.type == "attribution"}
    return tuple(ps | {"1y"})  # 1y always computed: the commentary uses it


def compose(db: Session, scheme: Scheme, spec: ReportSpec, period_end, gate_overridden: bool,
            commentary: Commentary | None = None) -> tuple[Analysis, Document, str]:
    """Build the analysis + document + fingerprint without writing any files."""
    blockers = material_blockers(db, scheme.id, period_end)
    gate_note = None
    if blockers:
        if not gate_overridden:
            listing = ", ".join(f"{b.fund.code} {b.month:%Y-%m} ({b.break_type.replace('_', ' ')})" for b in blockers[:6])
            raise GateError(f"{len(blockers)} material reconciliation break(s) are unresolved: {listing}. "
                            f"Resolve them, or an admin can override the gate.")
        gate_note = (f"This report was released with {len(blockers)} unresolved material data difference(s) "
                     f"between the custodian and fund managers. Affected figures use custodian values and may change.")

    analysis = build_analysis(db, scheme, period_end, attribution_periods=_attr_periods(spec),
                              linking=spec.linking, with_simulation=_wants_simulation(spec))
    words = next((s.words for s in spec.sections if s.type == "commentary"), None)
    if words is not None and commentary is None:
        commentary = generate_commentary(analysis, words)
    elif commentary is not None:
        commentary.fact_ids = [f.id for f in fact_sheet(analysis)]
    doc = build_document(analysis, spec, commentary, _breaks_for_report(db, scheme.id, period_end), gate_note)
    used = analysis.facts.subset(doc.fact_ids())
    fp = fingerprint(doc, {f.id: f.value for f in used.all()})
    return analysis, doc, fp


def generate(db: Session, run: ReportRun) -> ReportRun:
    scheme = db.get(Scheme, run.scheme_id)
    spec = load_spec(run.spec_name)
    analysis, doc, fp = compose(db, scheme, spec, run.period_end, run.gate_overridden)

    out = run_dir(run.id)
    if out.exists():
        shutil.rmtree(out)
    (out / "charts").mkdir(parents=True)
    for section in doc.sections:
        for i, block in enumerate(section.blocks):
            if isinstance(block, Chart):
                png = out / "charts" / f"{block.chart}.png"
                charts.RENDERERS[block.chart](block.data, png)
                section.blocks[i] = replace(block, image=str(png))

    outputs = {}
    base = f"{scheme.code}_{spec.name}_{run.period_end:%Y-%m}"
    if "docx" in spec.formats:
        outputs["docx"] = str(render_docx(doc, out / f"{base}.docx").relative_to(settings.storage_dir))
    if "pptx" in spec.formats:
        outputs["pptx"] = str(render_pptx(doc, out / f"{base}.pptx").relative_to(settings.storage_dir))
    if "html" in spec.formats:
        outputs["html"] = str(render_html(doc, analysis.facts, fp, out / f"{base}.html").relative_to(settings.storage_dir))

    db.execute(delete(LineageFact).where(LineageFact.report_run_id == run.id))
    used = analysis.facts.subset(doc.fact_ids())
    db.add_all([LineageFact(report_run_id=run.id, fact_id=f.id, label=f.label, value=f.value, unit=f.unit,
                            formula=f.formula, inputs=f.inputs, sources=f.sources) for f in used.all()])

    commentary = next((b for s in doc.sections for b in s.blocks if isinstance(b, Commentary)), None)
    run.fingerprint = fp
    run.outputs = outputs
    run.data_versions = analysis.data_versions
    run.commentary_status = commentary.status if commentary else None
    run.commentary_issues = commentary.issues if commentary else []
    run.commentary_text = commentary.text if commentary else None
    run.commentary_provider = commentary.provider if commentary else None
    run.status = "done"
    run.error = None
    run.finished_at = utcnow()
    audit(db, run.created_by, "report.generate", "report_run", run.id, fingerprint=fp[:16], spec=spec.name,
          commentary=run.commentary_status, facts=len(used.all()))
    db.commit()
    return run


def reproduce(db: Session, run: ReportRun) -> dict:
    """Rebuild a past report from the current data and compare content fingerprints.

    The stored commentary text is reused (LLM output is not deterministic) but it is
    re-verified against the freshly computed numbers, so stale prose is caught too.
    """
    scheme = db.get(Scheme, run.scheme_id)
    spec = load_spec(run.spec_name)
    stored = None
    if run.commentary_text is not None:
        stored = Commentary(run.commentary_text, run.commentary_status or "verified",
                            run.commentary_provider or "unknown", run.commentary_issues or [], [])
    try:
        analysis, doc, fp = compose(db, scheme, spec, run.period_end, run.gate_overridden, commentary=stored)
    except GateError as exc:
        return {"report_id": run.id, "original_fingerprint": run.fingerprint, "current_fingerprint": None,
                "identical": False, "blocked": str(exc), "changed_facts": [], "n_changed_facts": 0,
                "commentary_still_valid": None, "commentary_issues": []}
    old = {f.fact_id: f.value for f in db.scalars(select(LineageFact).where(LineageFact.report_run_id == run.id))}
    used = analysis.facts.subset(doc.fact_ids())
    new = {f.id: f.value for f in used.all()}
    changes = diff_facts(old, new)
    commentary_issues = _check(run.commentary_text, fact_sheet(analysis)) if run.commentary_text else []
    return {
        "report_id": run.id,
        "original_fingerprint": run.fingerprint,
        "current_fingerprint": fp,
        "identical": fp == run.fingerprint,
        "changed_facts": changes[:200],
        "n_changed_facts": len(changes),
        "commentary_still_valid": not commentary_issues,
        "commentary_issues": commentary_issues,
    }


def compare_runs(db: Session, a: ReportRun, b: ReportRun) -> dict:
    fa = {f.fact_id: (f.value, f.label, f.unit) for f in db.scalars(select(LineageFact).where(LineageFact.report_run_id == a.id))}
    fb = {f.fact_id: (f.value, f.label, f.unit) for f in db.scalars(select(LineageFact).where(LineageFact.report_run_id == b.id))}
    changes = diff_facts({k: v[0] for k, v in fa.items()}, {k: v[0] for k, v in fb.items()})
    for c in changes:
        meta = fb.get(c["fact_id"]) or fa.get(c["fact_id"])
        c["label"], c["unit"] = meta[1], meta[2]
    return {"a": a.id, "b": b.id, "same_fingerprint": a.fingerprint == b.fingerprint, "changes": changes}
