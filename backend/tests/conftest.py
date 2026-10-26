"""Test configuration: isolated SQLite DB + storage dir per test session."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ledgerline-tests-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["AI_PROVIDER"] = "mock"
os.environ["EMBEDDED_WORKER"] = "false"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Scheme  # noqa: E402
from app.seed.__main__ import SAMPLE_DIR, seed  # noqa: E402


@pytest.fixture()
def seeded():
    """A freshly seeded database (sample scheme + data + reconciliation)."""
    from app.analytics import cache

    cache.clear()
    seed(reset=True, verbose=False)
    yield
    cache.clear()


@pytest.fixture()
def db(seeded):
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def scheme(db):
    return db.scalar(select(Scheme).where(Scheme.code == "NBPS"))


@pytest.fixture()
def sample_dir() -> Path:
    return SAMPLE_DIR


def resolve_all_breaks(db, scheme, actor="analyst@ledgerline.dev"):
    """Upload the custodian correction, then resolve whatever is left, like an analyst would."""
    from app.ingestion.loader import load_file
    from app.recon.engine import open_breaks, resolve_break, run_reconciliation

    fname = "custodian_correction_PRP_2026-07.csv"
    load_file(db, scheme, "custodian_csv", fname, (SAMPLE_DIR / fname).read_bytes(), actor)
    run_reconciliation(db, scheme, actor)
    reasons = {
        "GEQ": ("custodian", "Manager quoted gross of fees; net-of-fee custodian figure is correct"),
        "EME": ("custodian", "Sign error in manager pack confirmed by manager by email"),
        "DGF": ("custodian", "Manager figure not yet published; custodian valuation used"),
        "CRD": ("custodian", "Pricing-source timing difference within expected range"),
    }
    for brk in open_breaks(db, scheme.id):
        resolution, reason = reasons.get(brk.fund.code, ("custodian", "Reviewed and accepted custodian value"))
        resolve_break(db, brk, resolution, actor, reason)
    db.commit()
