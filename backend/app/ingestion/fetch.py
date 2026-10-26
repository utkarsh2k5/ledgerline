"""Fetch real market data into Ledgerline's file formats (run on your own machine).

Examples
--------
    # Indian mutual fund NAV history from mfapi.in -> benchmark CSV for fund GEQ
    python -m app.ingestion.fetch mfapi <scheme_code> GEQ > data/real/geq_benchmark.csv

    # Then upload it through the UI (Data > Upload, adapter "benchmark_csv")
    # or: python -m app.cli ingest NBPS benchmark_csv data/real/geq_benchmark.csv

US Treasury par yield curve CSVs can be downloaded directly from
home.treasury.gov and uploaded with the "us_treasury_par_csv" adapter.
"""
from __future__ import annotations

import sys

import httpx

from .adapters import mfapi_to_benchmark_csv

MFAPI_URL = "https://api.mfapi.in/mf/{code}"


def fetch_mfapi(scheme_code: str, fund_code: str) -> str:
    resp = httpx.get(MFAPI_URL.format(code=scheme_code), timeout=30)
    resp.raise_for_status()
    return mfapi_to_benchmark_csv(resp.json(), fund_code.upper())


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "mfapi":
        print(__doc__)
        return 2
    sys.stdout.write(fetch_mfapi(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
