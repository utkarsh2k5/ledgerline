"""Command-line interface (useful for scripting, CI and demos).

    python -m app.cli ingest NBPS custodian_csv path/to/file.csv
    python -m app.cli recon NBPS
    python -m app.cli report NBPS quarterly_trustee_report --period-end 2026-09-30
    python -m app.cli demo --out ../sample_output      # end-to-end demo, writes sample reports
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from .config import settings
from .db import SessionLocal, init_db
from .ingestion.loader import IngestionError, load_file
from .models import ReportRun, Scheme
from .recon.engine import open_breaks, resolve_break, run_reconciliation
from .reporting.pipeline import generate


def _scheme(db, code: str) -> Scheme:
    s = db.scalar(select(Scheme).where(Scheme.code == code))
    if s is None:
        sys.exit(f"Unknown scheme {code}")
    return s


def cmd_ingest(a) -> None:
    with SessionLocal() as db:
        s = _scheme(db, a.scheme)
        path = Path(a.file)
        try:
            res = load_file(db, s, a.adapter, path.name, path.read_bytes(), "cli")
        except IngestionError as exc:
            for i in exc.report.errors:
                print(f"ERROR {i.row_ref or ''}: {i.message}")
            sys.exit(1)
        if not res.duplicate and res.version.source in {"custodian", "manager"}:
            run_reconciliation(db, s, "cli")
        db.commit()
        print("Already loaded" if res.duplicate else f"Loaded dataset v{res.version.id} ({res.version.row_count} rows)")


def cmd_recon(a) -> None:
    with SessionLocal() as db:
        s = _scheme(db, a.scheme)
        summ = run_reconciliation(db, s, "cli")
        db.commit()
        print(f"{summ.run.n_compared} compared, {summ.run.n_breaks} breaks, "
              f"{summ.open_material} material open, {summ.open_minor} minor open")
        for b in open_breaks(db, s.id):
            print(f"  #{b.id} {b.fund.code} {b.month} {b.break_type} {b.severity}")


def _report(db, s: Scheme, spec: str, period_end: date, override: bool) -> ReportRun:
    run = ReportRun(scheme_id=s.id, spec_name=spec, period_end=period_end, created_by="cli", gate_overridden=override)
    db.add(run)
    db.commit()
    return generate(db, run)


def cmd_report(a) -> None:
    with SessionLocal() as db:
        s = _scheme(db, a.scheme)
        run = _report(db, s, a.spec, date.fromisoformat(a.period_end), a.override)
        for fmt, rel in run.outputs.items():
            print(f"{fmt}: {settings.storage_dir / rel}")
        print(f"fingerprint {run.fingerprint[:16]}  commentary: {run.commentary_status}")


def cmd_demo(a) -> None:
    """Seed -> upload correction -> resolve breaks -> generate both specs -> copy outputs."""
    from .seed.__main__ import SAMPLE_DIR, seed

    seed(reset=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        s = _scheme(db, "NBPS")
        f = "custodian_correction_PRP_2026-07.csv"
        load_file(db, s, "custodian_csv", f, (SAMPLE_DIR / f).read_bytes(), "analyst@ledgerline.dev")
        run_reconciliation(db, s, "analyst@ledgerline.dev")
        reasons = {
            "GEQ": "Manager quoted gross of fees; the custodian's net-of-fee figure is correct",
            "EME": "Sign error in the manager pack, confirmed by the manager",
            "DGF": "Manager figure not yet published; custodian valuation used",
            "CRD": "Pricing-source timing difference within expected range",
        }
        for b in open_breaks(db, s.id):
            resolve_break(db, b, "custodian", "analyst@ledgerline.dev", reasons.get(b.fund.code, "Reviewed"))
        db.commit()
        for spec in ("quarterly_trustee_report", "trustee_summary"):
            run = _report(db, s, spec, date(2026, 9, 30), False)
            for fmt, rel in run.outputs.items():
                shutil.copy(settings.storage_dir / rel, out / Path(rel).name)
            print(f"{spec}: {sorted(run.outputs)} fingerprint {run.fingerprint[:12]} commentary {run.commentary_status}")
    print(f"Sample outputs written to {out.resolve()}")


def main(argv: list[str] | None = None) -> None:
    init_db()
    p = argparse.ArgumentParser(prog="ledgerline")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("scheme"); i.add_argument("adapter"); i.add_argument("file")
    i.set_defaults(fn=cmd_ingest)
    r = sub.add_parser("recon")
    r.add_argument("scheme")
    r.set_defaults(fn=cmd_recon)
    g = sub.add_parser("report")
    g.add_argument("scheme"); g.add_argument("spec")
    g.add_argument("--period-end", default="2026-09-30")
    g.add_argument("--override", action="store_true")
    g.set_defaults(fn=cmd_report)
    d = sub.add_parser("demo")
    d.add_argument("--out", default="../sample_output")
    d.set_defaults(fn=cmd_demo)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
