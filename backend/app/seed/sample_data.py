"""Generates a realistic (fictional) DB pension scheme dataset.

The Northbridge Engineering Pension Scheme is made up; all numbers are
simulated with a fixed seed so outputs are reproducible.

Deliberately planted problems (so reconciliation has something to find):
  * GEQ  2026-05  manager reported gross of fees           (~31 bps, material)
  * EME  2026-08  manager sign error on the return           (material)
  * DGF  2026-09  manager left the month blank               (missing)
  * PRP  2026-07/08 custodian used a stale property valuation (material, both months)
                    -> fixed by the custodian correction file (dataset v2)
  * CRD  2026-06  small difference of ~9 bps                  (minor)

Usage:  python -m app.seed.sample_data <output_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from ..funding.curve import bootstrap
from ..funding.liabilities import pv01, present_value

SEED = 1601
START, END = "2023-10-31", "2026-09-30"
INITIAL_TOTAL = 1_250_000_000.0

FUNDS = [
    # code, name, asset class, manager, benchmark, target, start weight, ann mu, ann vol, alpha, te, growth, duration
    ("GEQ", "Global Equity", "Global equities", "Ashgrove Capital", "Global equity index (GBP)", 0.25, 0.27, 0.080, 0.140, 0.010, 0.030, True, 0.0),
    ("EME", "Emerging Markets Equity", "EM equities", "Larkfield Investors", "EM equity index (GBP)", 0.10, 0.09, 0.070, 0.180, -0.015, 0.040, True, 0.0),
    ("DGF", "Diversified Growth", "Multi-asset", "Halden Multi-Asset", "SONIA + 4% p.a.", 0.10, 0.10, 0.060, 0.070, -0.005, 0.025, True, 0.0),
    ("PRP", "UK Property", "Real estate", "Corran Real Estate", "UK property index", 0.10, 0.11, 0.050, 0.080, 0.005, 0.020, True, 0.0),
    ("CRD", "Buy & Maintain Credit", "Corporate bonds", "Thornbury Credit", "Sterling corporate bond index", 0.15, 0.14, 0.045, 0.060, 0.003, 0.008, False, 7.0),
    ("LDI", "Liability Driven Investment", "LDI", "Corvid LDI", "Scheme liability benchmark", 0.30, 0.29, 0.040, 0.140, 0.000, 0.004, False, None),
]

CORR = np.array([
    [1.00, 0.80, 0.60, 0.40, 0.20, 0.00],
    [0.80, 1.00, 0.55, 0.35, 0.20, 0.00],
    [0.60, 0.55, 1.00, 0.40, 0.35, 0.15],
    [0.40, 0.35, 0.40, 1.00, 0.20, 0.05],
    [0.20, 0.20, 0.35, 0.20, 1.00, 0.70],
    [0.00, 0.00, 0.15, 0.05, 0.70, 1.00],
])

PAR_CURVE = [(1, 3.85), (2, 3.80), (3, 3.82), (5, 3.95), (7, 4.10), (10, 4.35), (15, 4.70),
             (20, 4.95), (25, 5.05), (30, 5.05), (40, 4.90), (50, 4.75)]
TARGET_FUNDING_RATIO = 0.934
TARGET_HEDGE_RATIO = 0.82


def generate(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    months = pd.date_range(START, END, freq="ME")
    n, k = len(months), len(FUNDS)

    mu = np.array([f[7] for f in FUNDS]) / 12
    vol = np.array([f[8] for f in FUNDS]) / np.sqrt(12)
    cov = np.outer(vol, vol) * CORR
    bench = rng.multivariate_normal(mu, cov, size=n)                       # n x k
    alpha = np.array([f[9] for f in FUNDS]) / 12
    te = np.array([f[10] for f in FUNDS]) / np.sqrt(12)
    port = bench + alpha + rng.standard_normal((n, k)) * te

    # Cash flows: benefits out of LDI/credit, contributions into growth (by target weight)
    benefits, contributions = -4_500_000.0, 1_500_000.0
    flow_split = np.array([0.0, 0.0, 0.0, 0.0, 0.35, 0.65])
    contrib_split = np.array([0.5, 0.2, 0.2, 0.1, 0.0, 0.0])
    flows = np.round(benefits * flow_split + contributions * contrib_split + rng.normal(0, 150_000, k) * (flow_split > 0), 2)

    bmv = INITIAL_TOTAL * np.array([f[6] for f in FUNDS])
    rows, true_returns = [], np.zeros((n, k))
    for t, m in enumerate(months):
        f_t = flows * (1 + 0.1 * np.sin(t / 3))
        if t > 0 and t % 3 == 0:
            # quarterly rebalancing: move half-way back to the strategic weights
            target_w = np.array([f[5] for f in FUNDS])
            f_t = f_t + 0.5 * (target_w * bmv.sum() - bmv)
        f_t = np.round(f_t, 2)
        r = port[t]
        emv = bmv * (1 + r) + f_t * (1 + r / 2)                              # mid-month flows
        emv = np.round(emv, 2)
        for i, f in enumerate(FUNDS):
            rows.append({"fund_code": f[0], "month": m.date(), "begin_mv": round(bmv[i], 2),
                         "end_mv": emv[i], "net_flow": f_t[i]})
        bmv = emv
    cust = pd.DataFrame(rows)
    cust["ret"] = (cust["end_mv"] - cust["begin_mv"] - cust["net_flow"]) / (cust["begin_mv"] + 0.5 * cust["net_flow"])

    # --- custodian file with a stale PRP valuation (Jul 2026 understated, caught up in Aug)
    original = cust.copy()
    sel_jul = (original["fund_code"] == "PRP") & (original["month"] == pd.Timestamp("2026-07-31").date())
    sel_aug = (original["fund_code"] == "PRP") & (original["month"] == pd.Timestamp("2026-08-31").date())
    stale_delta = round(float(original.loc[sel_jul, "begin_mv"].iloc[0]) * 0.0042, 2)
    original.loc[sel_jul, "end_mv"] -= stale_delta
    original.loc[sel_aug, "begin_mv"] -= stale_delta

    def write_custodian(df: pd.DataFrame, path: Path) -> None:
        out = df.rename(columns={"fund_code": "Fund Code", "month": "Month End", "begin_mv": "Opening Market Value",
                                 "end_mv": "Closing Market Value", "net_flow": "Net Cash Flow"})
        out = out[["Fund Code", "Month End", "Opening Market Value", "Closing Market Value", "Net Cash Flow"]]
        out.to_csv(path, index=False, float_format="%.2f")

    write_custodian(original, out_dir / "custodian_valuations_2023-10_to_2026-09.csv")
    correction = cust[sel_jul | sel_aug]
    write_custodian(correction, out_dir / "custodian_correction_PRP_2026-07.csv")

    # --- manager workbook (wide, percent, a few text formats)
    mgr = cust.pivot(index="fund_code", columns="month", values="ret").reindex([f[0] for f in FUNDS])
    mgr_pct = (mgr * 100).round(2).astype(object)
    mgr_pct.loc["GEQ", pd.Timestamp("2026-05-31").date()] = round(float(mgr.loc["GEQ", pd.Timestamp("2026-05-31").date()]) * 100 + 0.31, 2)
    eme_aug = pd.Timestamp("2026-08-31").date()
    mgr_pct.loc["EME", eme_aug] = round(-float(mgr.loc["EME", eme_aug]) * 100, 2)
    mgr_pct.loc["DGF", pd.Timestamp("2026-09-30").date()] = None
    crd_jun = pd.Timestamp("2026-06-30").date()
    mgr_pct.loc["CRD", crd_jun] = round(float(mgr.loc["CRD", crd_jun]) * 100 + 0.09, 2)
    _write_manager_workbook(mgr_pct, out_dir / "manager_performance_pack_Q3_2026.xlsx")

    # --- benchmarks
    bench_rows = [{"fund_code": f[0], "month_end": m.date(), "return_pct": round(bench[t, i] * 100, 4)}
                  for t, m in enumerate(months) for i, f in enumerate(FUNDS)]
    pd.DataFrame(bench_rows).to_csv(out_dir / "benchmark_returns.csv", index=False)

    # --- curve
    curve_df = pd.DataFrame([{"as_of": END, "tenor_years": t, "par_yield_pct": y} for t, y in PAR_CURVE])
    curve_df.to_csv(out_dir / "gilt_par_curve_2026-09-30.csv", index=False)
    curve = bootstrap([t for t, _ in PAR_CURVE], [y / 100 for _, y in PAR_CURVE], max_year=80)

    # --- liabilities: hump-shaped benefit profile, scaled to a target funding ratio
    years = np.arange(1, 71)
    shape = years ** 1.4 * np.exp(-years / 11.0) + 2.0 * np.exp(-years / 6.0)
    final_mv = cust[cust["month"] == months[-1].date()].set_index("fund_code")["end_mv"]
    total_assets = float(final_mv.sum())
    scale = (total_assets / TARGET_FUNDING_RATIO) / present_value(shape, curve)
    cashflows = np.round(shape * scale, 0)
    pd.DataFrame({"year": years, "cashflow": cashflows}).to_csv(out_dir / "liability_cashflows_actuary_2026.csv", index=False)

    # --- LDI duration so that the hedge ratio lands near the target
    liab_pv01 = pv01(cashflows, curve)
    crd_pv01 = final_mv["CRD"] * 7.0 * 1e-4
    ldi_duration = round((TARGET_HEDGE_RATIO * liab_pv01 - crd_pv01) / (final_mv["LDI"] * 1e-4), 1)

    config = {
        "code": "NBPS",
        "name": "Northbridge Engineering Pension Scheme",
        "sponsor": "Northbridge Engineering Ltd (fictional)",
        "currency": "GBP",
        "funds": [
            {"code": f[0], "name": f[1], "asset_class": f[2], "manager": f[3], "benchmark_name": f[4],
             "target_weight": f[5], "is_growth": f[11],
             "effective_duration": ldi_duration if f[0] == "LDI" else f[12], "sort_order": i}
            for i, f in enumerate(FUNDS)
        ],
    }
    (out_dir / "scheme.json").write_text(json.dumps(config, indent=2))

    _write_bad_file(out_dir / "examples_with_errors" / "custodian_with_errors.csv")
    return config


def _write_manager_workbook(mgr_pct: pd.DataFrame, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Monthly Returns"
    ws["A1"] = "Northbridge Engineering Pension Scheme - Manager performance pack"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Returns in % (net of fees), month-end. Compiled from manager submissions."
    header = ["Fund"] + [pd.Timestamp(m).strftime("%b-%y") for m in mgr_pct.columns]
    ws.append([])
    ws.append(header)
    for cell in ws[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
    for r, (code, values) in enumerate(mgr_pct.iterrows()):
        row = [code]
        for c, v in enumerate(values):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                row.append("n/a")
            elif (r + c) % 11 == 0 and float(v) < 0:
                row.append(f"({abs(float(v)):.2f})")       # accounting negative as text
            elif (r + c) % 7 == 0:
                row.append(f"{float(v):.2f}%")             # percent stored as text
            else:
                row.append(float(v))
        ws.append(row)
    ws.append([])
    ws.append(["Note: figures are unaudited."])
    ws.column_dimensions["A"].width = 10
    wb.save(path)


def _write_bad_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Fund Code,Month End,Opening Market Value,Closing Market Value,Net Cash Flow\n"
        "GEQ,2026-10-31,310000000.00,312500000.00,0\n"
        "GEQ,2026-10-31,310000000.00,312500000.00,0\n"
        "EME,2026-10-31,-5000.00,118000000.00,0\n"
        "XYZ,2026-10-31,1000.00,1100.00,0\n"
        "DGF,not a date,125000000.00,126000000.00,0\n"
        "PRP,2026-10-31,140000000.00,twelve million,0\n"
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/sample")
    cfg = generate(target)
    print(f"Wrote sample data for {cfg['name']} to {target}")
