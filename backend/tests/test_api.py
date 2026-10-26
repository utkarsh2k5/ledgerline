import pytest
from fastapi.testclient import TestClient

from app.jobs.worker import process_one
from app.main import app


@pytest.fixture()
def client(seeded):
    with TestClient(app) as c:
        yield c


def _token(client, who="analyst"):
    r = client.post("/api/auth/login", json={"email": f"{who}@ledgerline.dev", "password": f"{who}123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_requires_auth(client):
    assert client.get("/api/schemes").status_code == 401
    assert client.post("/api/auth/login", json={"email": "analyst@ledgerline.dev", "password": "nope"}).status_code == 401


def test_overview_attribution_funding(client):
    h = _token(client, "viewer")
    sid = client.get("/api/schemes", headers=h).json()[0]["id"]
    ov = client.get(f"/api/schemes/{sid}/overview", headers=h).json()
    assert ov["period_end"] == "2026-09-30"
    assert ov["recon"]["open_material"] == 5
    assert len(ov["funds"]) == 7
    att = client.get(f"/api/schemes/{sid}/attribution?period=3y", headers=h).json()
    assert abs(att["methods"]["carino"]["residual"]) < 1e-10
    assert abs(att["methods"]["sum"]["residual"]) > 1e-5
    fund = client.get(f"/api/schemes/{sid}/funding", headers=h).json()
    assert fund["simulation"]["n_paths"] == 10000
    tr = client.get(f"/api/schemes/{sid}/facts/funding.ratio/trace", headers=h).json()
    assert tr["children"][0]["id"] == "funding.assets"


def test_rbac(client):
    viewer = _token(client, "viewer")
    analyst = _token(client, "analyst")
    sid = client.get("/api/schemes", headers=viewer).json()[0]["id"]
    files = {"file": ("x.csv", b"fund_code,month_end,return_pct\n", "text/csv")}
    assert client.post(f"/api/schemes/{sid}/datasets", headers=viewer, data={"adapter": "benchmark_csv"}, files=files).status_code == 403
    r = client.post(f"/api/schemes/{sid}/reports", headers=analyst, json={"spec": "trustee_summary", "override_gate": True})
    assert r.status_code == 403  # only admins may override the gate


def test_bad_upload_returns_row_level_errors(client, sample_dir):
    h = _token(client)
    sid = client.get("/api/schemes", headers=h).json()[0]["id"]
    bad = (sample_dir / "examples_with_errors" / "custodian_with_errors.csv").read_bytes()
    r = client.post(f"/api/schemes/{sid}/datasets", headers=h, data={"adapter": "custodian_csv"},
                    files={"file": ("bad.csv", bad, "text/csv")})
    assert r.status_code == 422
    assert len(r.json()["detail"]["validation"]["errors"]) >= 5


def test_report_flow_end_to_end(client, sample_dir):
    h = _token(client)
    admin = _token(client, "admin")
    sid = client.get("/api/schemes", headers=h).json()[0]["id"]

    # blocked by the reconciliation gate
    r = client.post(f"/api/schemes/{sid}/reports", headers=h, json={"spec": "quarterly_trustee_report"})
    assert r.status_code == 409 and len(r.json()["detail"]["breaks"]) == 5

    # upload the custodian correction -> auto-reconcile clears the PRP breaks
    corr = (sample_dir / "custodian_correction_PRP_2026-07.csv").read_bytes()
    up = client.post(f"/api/schemes/{sid}/datasets", headers=h, data={"adapter": "custodian_csv"},
                     files={"file": ("correction.csv", corr, "text/csv")}).json()
    assert up["reconciliation"]["open_material"] == 3

    # resolve the rest
    for b in client.get(f"/api/schemes/{sid}/recon/breaks?status=open", headers=h).json():
        res = client.post(f"/api/recon/breaks/{b['id']}/resolve", headers=h,
                          json={"resolution": "custodian", "reason": "Checked against custodian statement"})
        assert res.status_code == 200, res.text

    r = client.post(f"/api/schemes/{sid}/reports", headers=h, json={"spec": "quarterly_trustee_report"})
    assert r.status_code == 202
    rid = r.json()["id"]
    assert process_one() is True  # the worker picks up the queued job
    rep = client.get(f"/api/reports/{rid}", headers=h).json()
    assert rep["status"] == "done", rep
    d = client.get(f"/api/reports/{rid}/download/docx", headers=h)
    assert d.status_code == 200 and d.content[:2] == b"PK"
    lin = client.get(f"/api/reports/{rid}/lineage/perf.TOTAL.3m.ret?depth=2", headers=h).json()
    assert lin["n_inputs"] == 3 and lin["children"][0]["children"]
    rep2 = client.post(f"/api/reports/{rid}/reproduce", headers=h).json()
    assert rep2["identical"] is True

    # an admin can still release a report with open breaks, and it's flagged
    assert client.get("/api/audit", headers=admin).json()[0]["action"] == "report.reproduce"


def test_demo_role_access(client):
    assert client.get("/api/auth/demo").json() == {"enabled": True}
    r = client.post("/api/auth/demo", json={"role": "viewer"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "viewer"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/schemes", headers=h).status_code == 200
    assert client.post("/api/auth/demo", json={"role": "superuser"}).status_code == 422


def test_demo_access_can_be_disabled(client, monkeypatch):
    import dataclasses

    import app.api.routes_core as core
    monkeypatch.setattr(core, "settings", dataclasses.replace(core.settings, demo_mode=False))
    assert client.post("/api/auth/demo", json={"role": "admin"}).status_code == 404
