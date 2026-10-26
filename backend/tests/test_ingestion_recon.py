import io

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings as hsettings
from hypothesis import strategies as st
from openpyxl import Workbook
from sqlalchemy import select

from app.ingestion.adapters import ADAPTERS
from app.ingestion.loader import IngestionError, load_file
from app.models import DatasetVersion, ReconBreak
from app.recon.engine import compare, golden_returns, open_breaks, resolve_break, run_reconciliation


# ---- adapters -------------------------------------------------------------------

def _wb_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Returns"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_manager_excel_handles_messy_formats():
    content = _wb_bytes([
        ["Some title"], [],
        ["Fund", "Jan-26", "Feb-26", "Mar-26"],
        ["geq", 1.25, "(0.40)", "2.10%"],
        ["EME", "n/a", -0.5, ""],
        ["Total", 1, 1, 1],
    ])
    df = ADAPTERS["manager_excel"].parse(content, "pack.xlsx")
    got = {(r.fund_code, str(r.month)): r.reported_return for r in df.itertuples()}
    assert got[("GEQ", "2026-01-31")] == pytest.approx(0.0125)
    assert got[("GEQ", "2026-02-28")] == pytest.approx(-0.004)
    assert got[("GEQ", "2026-03-31")] == pytest.approx(0.021)
    assert np.isnan(got[("EME", "2026-01-31")])
    assert ("TOTAL", "2026-01-31") not in got
    assert df.loc[0, "row_ref"] == "pack.xlsx!Returns!B4"


def test_contract_rejects_bad_file_with_row_level_errors(db, scheme, sample_dir):
    bad = (sample_dir / "examples_with_errors" / "custodian_with_errors.csv").read_bytes()
    with pytest.raises(IngestionError) as exc:
        load_file(db, scheme, "custodian_csv", "bad.csv", bad, "test")
    messages = " | ".join(i.message for i in exc.value.report.errors)
    assert "Duplicate row" in messages
    assert "non-negative" in messages
    assert "Unknown fund code 'XYZ'" in messages
    assert "not a date" in messages
    assert "not a number" in messages
    assert all(i.row_ref for i in exc.value.report.errors if "Duplicate" not in i.message)


def test_loading_is_idempotent_even_if_rows_are_reordered(db, scheme, sample_dir):
    raw = (sample_dir / "benchmark_returns.csv").read_text()
    header, *lines = raw.strip().splitlines()
    shuffled = "\n".join([header] + lines[::-1]) + "\n"
    res = load_file(db, scheme, "benchmark_csv", "reordered.csv", shuffled.encode(), "test")
    assert res.duplicate is True
    n_versions = db.scalar(select(DatasetVersion.id).order_by(DatasetVersion.id.desc()))
    assert n_versions == 5  # nothing new was stored


# ---- reconciliation ----------------------------------------------------------------

def _frames(cust_ret, mgr_ret):
    custodian = pd.DataFrame({"fund_id": [1], "month": [pd.Timestamp("2026-01-31").date()],
                              "begin_mv": [100.0], "end_mv": [100.0 * (1 + cust_ret)], "net_flow": [0.0],
                              "row_ref": ["c#2"]})
    manager = pd.DataFrame({"fund_id": [1], "month": [pd.Timestamp("2026-01-31").date()],
                            "reported_return": [mgr_ret], "row_ref": ["m!B4"]})
    return custodian, manager


@hsettings(max_examples=100, deadline=None)
@given(st.floats(-0.1, 0.1), st.floats(-0.01, 0.01))
def test_break_iff_difference_exceeds_tolerance(r, diff):
    c, m = _frames(r, r + diff)
    out = compare(c, m, tolerance_bps=5, material_bps=25).iloc[0]
    if abs(diff) * 1e4 > 5 + 1e-6:
        assert out.break_type == "value_mismatch"
        assert out.severity == ("material" if abs(diff) * 1e4 > 25 + 1e-6 else "minor")
    elif abs(diff) * 1e4 < 5 - 1e-6:
        assert out.break_type == "matched"


def test_seeded_reconciliation_finds_planted_breaks(db, scheme):
    found = {(b.fund.code, b.month.isoformat(), b.break_type, b.severity) for b in open_breaks(db, scheme.id)}
    assert found == {
        ("GEQ", "2026-05-31", "value_mismatch", "material"),
        ("EME", "2026-08-31", "value_mismatch", "material"),
        ("DGF", "2026-09-30", "missing_manager", "material"),
        ("PRP", "2026-07-31", "value_mismatch", "material"),
        ("PRP", "2026-08-31", "value_mismatch", "material"),
        ("CRD", "2026-06-30", "value_mismatch", "minor"),
    }


def test_custodian_correction_supersedes_breaks(db, scheme, sample_dir):
    fname = "custodian_correction_PRP_2026-07.csv"
    res = load_file(db, scheme, "custodian_csv", fname, (sample_dir / fname).read_bytes(), "test")
    assert not res.duplicate
    run_reconciliation(db, scheme, "test")
    codes = {b.fund.code for b in open_breaks(db, scheme.id)}
    assert "PRP" not in codes
    superseded = db.scalars(select(ReconBreak).where(ReconBreak.status == "superseded")).all()
    assert {b.fund.code for b in superseded} == {"PRP"}


def test_resolution_survives_rerun_and_feeds_golden_source(db, scheme):
    brk = next(b for b in open_breaks(db, scheme.id) if b.fund.code == "GEQ")
    resolve_break(db, brk, "manager", "tester", "Manager confirmed the custodian missed a fee rebate")
    run_reconciliation(db, scheme, "test")
    db.refresh(brk)
    assert brk.status == "resolved"
    golden = golden_returns(db, scheme)
    row = golden[(golden.fund_id == brk.fund_id) & (golden.month == brk.month)].iloc[0]
    assert row.ret == pytest.approx(brk.manager_value)
    assert row.origin == "manager"
    assert any("recon_break" in ref for ref in row.row_refs)


def test_resolution_requires_reason_and_sane_override(db, scheme):
    brk = open_breaks(db, scheme.id)[0]
    with pytest.raises(ValueError):
        resolve_break(db, brk, "custodian", "tester", "")
    with pytest.raises(ValueError):
        resolve_break(db, brk, "override", "tester", "Typed the percentage", override_value=1.25)
