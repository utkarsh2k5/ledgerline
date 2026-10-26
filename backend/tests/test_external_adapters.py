"""Real-data adapters, tested offline against recorded fixtures."""
import pytest

from app.ingestion.adapters import ADAPTERS, mfapi_to_benchmark_csv

TREASURY_CSV = (
    "Date,1 Mo,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr\n"
    "09/29/2026,4.10,4.08,4.05,4.01,3.95,3.80,3.62,3.58,3.66,3.80,4.02,4.48,4.55\n"
    "09/30/2026,4.11,4.09,4.06,4.02,3.96,3.81,3.63,3.59,3.67,3.81,4.03,4.49,4.56\n"
)

MFAPI_JSON = {
    "meta": {"scheme_name": "Example Fund - Direct Growth"},
    "data": [  # newest first, as mfapi.in returns it
        {"date": "30-09-2026", "nav": "110.0"},
        {"date": "15-09-2026", "nav": "108.0"},
        {"date": "29-08-2026", "nav": "100.0"},
        {"date": "31-07-2026", "nav": "104.0"},
    ],
}


def test_treasury_par_curve_uses_latest_date():
    df = ADAPTERS["us_treasury_par_csv"].parse(TREASURY_CSV.encode(), "par.csv")
    assert set(df["as_of"].astype(str)) == {"2026-09-30"}
    ten = df[df["tenor_years"] == 10].iloc[0]
    assert ten["par_yield"] == pytest.approx(0.0403)
    assert df["tenor_years"].min() == pytest.approx(1 / 12)
    assert len(df) == 13


def test_mfapi_month_end_returns():
    csv = mfapi_to_benchmark_csv(MFAPI_JSON, "GEQ").strip().splitlines()
    assert csv[0] == "fund_code,month_end,return_pct"
    rows = {line.split(",")[1]: float(line.split(",")[2]) for line in csv[1:]}
    assert rows["2026-08-31"] == pytest.approx((100 / 104 - 1) * 100)
    assert rows["2026-09-30"] == pytest.approx(10.0)  # uses the month's last NAV, not mid-month


def test_mfapi_output_loads_through_benchmark_adapter():
    csv = mfapi_to_benchmark_csv(MFAPI_JSON, "GEQ")
    df = ADAPTERS["benchmark_csv"].parse(csv.encode(), "geq.csv")
    assert list(df["fund_code"].unique()) == ["GEQ"]
    assert df["ret"].iloc[-1] == pytest.approx(0.10)
