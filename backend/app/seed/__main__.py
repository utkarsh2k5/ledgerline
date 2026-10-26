"""Seed a fresh database with demo users, the sample scheme and its data.

    python -m app.seed            # idempotent; safe to run repeatedly
    python -m app.seed --reset    # drop and recreate all tables first
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import select

from ..auth import hash_password
from ..config import PROJECT_DIR
from ..db import Base, SessionLocal, engine, init_db
from ..ingestion.loader import load_file
from ..models import Fund, Scheme, User
from ..recon.engine import run_reconciliation
from .sample_data import generate

SAMPLE_DIR = PROJECT_DIR / "data" / "sample"

DEMO_USERS = [
    ("admin@ledgerline.dev", "Asha Admin", "admin", "admin123"),
    ("analyst@ledgerline.dev", "Ravi Analyst", "analyst", "analyst123"),
    ("viewer@ledgerline.dev", "Tara Trustee", "viewer", "viewer123"),
]

INITIAL_LOADS = [
    ("custodian_csv", "custodian_valuations_2023-10_to_2026-09.csv"),
    ("manager_excel", "manager_performance_pack_Q3_2026.xlsx"),
    ("benchmark_csv", "benchmark_returns.csv"),
    ("liabilities_csv", "liability_cashflows_actuary_2026.csv"),
    ("curve_csv", "gilt_par_curve_2026-09-30.csv"),
]


def seed(reset: bool = False, verbose: bool = True) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    init_db()
    if not (SAMPLE_DIR / "scheme.json").exists():
        generate(SAMPLE_DIR)
    config = json.loads((SAMPLE_DIR / "scheme.json").read_text())

    with SessionLocal() as db:
        for email, name, role, pwd in DEMO_USERS:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(email=email, name=name, role=role, password_hash=hash_password(pwd)))

        scheme = db.scalar(select(Scheme).where(Scheme.code == config["code"]))
        if scheme is None:
            scheme = Scheme(code=config["code"], name=config["name"], currency=config["currency"],
                            sponsor=config["sponsor"])
            db.add(scheme)
            db.flush()
            for f in config["funds"]:
                db.add(Fund(scheme_id=scheme.id, **f))
            db.flush()

        for adapter, filename in INITIAL_LOADS:
            res = load_file(db, scheme, adapter, filename, (SAMPLE_DIR / filename).read_bytes(), "seed")
            if verbose:
                state = "already loaded" if res.duplicate else f"loaded as dataset v{res.version.id}"
                print(f"  {filename}: {state} ({len(res.report.warnings)} warnings)")
        summary = run_reconciliation(db, scheme, "seed")
        db.commit()
        if verbose:
            print(f"  Reconciliation: {summary.run.n_compared} compared, {summary.run.n_breaks} breaks "
                  f"({summary.open_material} material open, {summary.open_minor} minor open)")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
    print("Seed complete. Demo logins: admin@ledgerline.dev/admin123, analyst@ledgerline.dev/analyst123, "
          "viewer@ledgerline.dev/viewer123")
