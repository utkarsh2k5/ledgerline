"""Source adapters: messy real-world files in, tidy normalised frames out.

Every adapter returns a DataFrame matching its contract plus a ``row_ref``
column (``file!sheet!cell`` or ``file#row``) so any number can later be traced
back to the exact cell it came from.

Adding a new source (a custodian's new format, a vendor API) means adding one
class here and registering it; nothing downstream changes.
"""
from __future__ import annotations

import io
import json
import re
from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

_NA_TOKENS = {"", "n/a", "na", "-", "--", "nan", "none", "null", "tbc"}


_MONTH_FORMATS = ("%b-%y", "%b %y", "%b-%Y", "%b %Y", "%B %Y", "%Y-%m", "%m/%Y", "%Y-%m-%d", "%d/%m/%Y")


# Explicit formats first: pandas' guesser read the manager pack's "Oct-23" header as
# 23 October of year 1, which silently produced 216 "duplicate" rows on first load.
def _parse_one_month(value: object) -> pd.Timestamp:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return pd.NaT
    if isinstance(value, (pd.Timestamp,)) or hasattr(value, "year"):
        return pd.Timestamp(value)
    text = str(value).strip()
    for fmt in _MONTH_FORMATS:
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt))
        except (ValueError, TypeError):
            continue
    try:
        return pd.Timestamp(pd.to_datetime(text))
    except (ValueError, TypeError):
        return pd.NaT


def month_end(values: pd.Series) -> pd.Series:
    """Normalise any month/date representation to a month-end date (NaT if unparseable or absurd)."""
    parsed = pd.Series([_parse_one_month(v) for v in values], index=values.index, dtype="datetime64[ns]")
    parsed = parsed.where((parsed.dt.year >= 1990) & (parsed.dt.year <= 2100))
    out = (parsed + pd.offsets.MonthEnd(0)).dt.date.astype(object)
    # keep the raw text where parsing failed so the contract can report "not a date: '...'"
    raw_present = values.notna() & values.astype(str).str.strip().ne("")
    bad = parsed.isna() & raw_present
    out[bad] = values[bad].astype(str)
    out[parsed.isna() & ~raw_present] = None
    return out


def _clean_header(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _parse_pct(value: object) -> object:
    """'1.23%' / '1.23' / 1.23 -> 0.0123. Unparseable values pass through for the contract to flag."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) / 100.0
    text = str(value).strip().replace(",", "")
    if text.lower() in _NA_TOKENS:
        return np.nan
    if text.startswith("(") and text.endswith(")"):  # accounting negative: (1.20)
        text = "-" + text[1:-1]
    text = text.rstrip("%").strip()
    try:
        return float(text) / 100.0
    except ValueError:
        return value


def _parse_number(value: object) -> object:
    """'1,234.5' -> 1234.5, '(12)' -> -12. Unparseable values pass through for the contract to flag."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.lower() in _NA_TOKENS:
        return np.nan
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return value


class Adapter(ABC):
    name: ClassVar[str]
    source: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    def parse(self, content: bytes, filename: str) -> pd.DataFrame: ...


class CustodianCsvAdapter(Adapter):
    """Long-format custodian valuation file: one row per fund per month."""

    name = "custodian_csv"
    source = "custodian"
    description = "Custodian valuations CSV: fund_code, month_end, begin_mv, end_mv, net_flow"

    ALIASES = {
        "fund": "fund_code",
        "portfolio_code": "fund_code",
        "month_end": "month",
        "valuation_date": "month",
        "opening_mv": "begin_mv",
        "opening_market_value": "begin_mv",
        "closing_mv": "end_mv",
        "closing_market_value": "end_mv",
        "net_cash_flow": "net_flow",
        "flows": "net_flow",
    }

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        df.columns = [self.ALIASES.get(_clean_header(c), _clean_header(c)) for c in df.columns]
        df["row_ref"] = [f"{filename}#row{i + 2}" for i in range(len(df))]  # +2: header + 1-based
        if "fund_code" in df:
            df["fund_code"] = df["fund_code"].str.strip().str.upper().replace("", np.nan)
        if "month" in df:
            df["month"] = month_end(df["month"])
        for col in ("begin_mv", "end_mv", "net_flow"):
            if col in df:
                df[col] = df[col].map(_parse_number)
        return df


class ManagerExcelAdapter(Adapter):
    """Manager performance pack: wide Excel sheet, funds down the side, months across.

    Returns are quoted in percent, sometimes as text ('1.23%'), sometimes with
    accounting negatives ('(0.40)') and blanks for unreported months.
    """

    name = "manager_excel"
    source = "manager"
    description = "Manager returns workbook (wide: Fund code column + one column per month, values in %)"

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object)
        sheet_name, raw = self._find_sheet(sheets)
        header_row = self._find_header_row(raw)
        header = raw.iloc[header_row]
        fund_col = next(
            (c for c in raw.columns if _clean_header(header[c]) in {"fund", "fund_code", "code", "mandate"}),
            raw.columns[0],
        )
        month_cols = {c: header[c] for c in raw.columns if c != fund_col and pd.notna(header[c])}
        months = month_end(pd.Series(list(month_cols.values()), dtype=object))
        col_month = dict(zip(month_cols.keys(), months))

        records = []
        for r in range(header_row + 1, len(raw)):
            code = raw.iat[r, fund_col]
            if pd.isna(code) or not str(code).strip():
                continue
            code = str(code).strip().upper()
            if code.startswith(("TOTAL", "NOTE", "SOURCE")):
                continue
            for c, m in col_month.items():
                if m is None or pd.isna(m):
                    continue
                records.append(
                    {
                        "fund_code": code,
                        "month": m,
                        "reported_return": _parse_pct(raw.iat[r, c]),
                        "row_ref": f"{filename}!{sheet_name}!{get_column_letter(c + 1)}{r + 1}",
                    }
                )
        return pd.DataFrame.from_records(records, columns=["fund_code", "month", "reported_return", "row_ref"])

    # TODO: some managers only send quarterly packs. That needs a frequency on the
    # dataset and quarterly-vs-monthly reconciliation, which isn't handled yet.
    @staticmethod
    def _find_sheet(sheets: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
        for name, frame in sheets.items():
            if any(k in name.lower() for k in ("return", "perf")):
                return name, frame
        name = next(iter(sheets))
        return name, sheets[name]

    @staticmethod
    def _find_header_row(raw: pd.DataFrame) -> int:
        for r in range(min(len(raw), 15)):
            cells = [_clean_header(v) for v in raw.iloc[r].tolist() if pd.notna(v)]
            if any(c in {"fund", "fund_code", "code", "mandate"} for c in cells):
                return r
        return 0


class BenchmarkCsvAdapter(Adapter):
    name = "benchmark_csv"
    source = "benchmark"
    description = "Benchmark returns CSV: fund_code, month_end, return_pct"

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        df.columns = [_clean_header(c) for c in df.columns]
        df = df.rename(columns={"month_end": "month", "return_pct": "ret_pct"})
        out = pd.DataFrame(
            {
                "fund_code": df.get("fund_code", pd.Series(dtype=str)).str.strip().str.upper().replace("", np.nan),
                "month": month_end(df["month"]) if "month" in df else None,
                "ret": df["ret_pct"].map(_parse_pct) if "ret_pct" in df else None,
                "row_ref": [f"{filename}#row{i + 2}" for i in range(len(df))],
            }
        )
        return out


class LiabilityCsvAdapter(Adapter):
    name = "liabilities_csv"
    source = "liabilities"
    description = "Actuary's projected benefit cashflows CSV: year, cashflow"

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        df.columns = [_clean_header(c) for c in df.columns]
        df = df.rename(columns={"cashflow": "amount", "projected_cashflow": "amount"})
        out = pd.DataFrame(
            {
                "year": df.get("year", pd.Series(dtype=str)).map(_parse_number),
                "amount": df.get("amount", pd.Series(dtype=str)).map(_parse_number),
                "row_ref": [f"{filename}#row{i + 2}" for i in range(len(df))],
            }
        )
        return out


class CurveCsvAdapter(Adapter):
    name = "curve_csv"
    source = "curve"
    description = "Government par yield curve CSV: as_of, tenor_years, par_yield_pct"

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        df.columns = [_clean_header(c) for c in df.columns]
        return pd.DataFrame(
            {
                "as_of": pd.to_datetime(df.get("as_of"), errors="coerce").dt.date,
                "tenor_years": df.get("tenor_years", pd.Series(dtype=str)).map(_parse_number),
                "par_yield": df.get("par_yield_pct", pd.Series(dtype=str)).map(_parse_pct),
                "row_ref": [f"{filename}#row{i + 2}" for i in range(len(df))],
            }
        )


class TreasuryParYieldAdapter(Adapter):
    """US Treasury daily par yield curve CSV (home.treasury.gov), latest date only.

    Download from: Treasury > Interest Rate Statistics > Daily Treasury Par
    Yield Curve Rates > CSV. Columns look like: Date, 1 Mo, 2 Mo, ..., 30 Yr.
    """

    name = "us_treasury_par_csv"
    source = "curve"
    description = "US Treasury daily par yield curve CSV (uses the most recent date in the file)"

    @staticmethod
    def _tenor(label: str) -> float | None:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mo|yr)\s*", label.lower())
        if not m:
            return None
        n = float(m.group(1))
        return n / 12.0 if m.group(2) == "mo" else n

    def parse(self, content: bytes, filename: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content))
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        latest_idx = df["Date"].idxmax()
        latest = df.loc[latest_idx]
        rows = []
        for col in df.columns:
            tenor = self._tenor(str(col))
            if tenor is None or pd.isna(latest[col]):
                continue
            rows.append(
                {
                    "as_of": latest["Date"].date(),
                    "tenor_years": tenor,
                    "par_yield": float(latest[col]) / 100.0,
                    "row_ref": f"{filename}#row{latest_idx + 2}:{col}",
                }
            )
        return pd.DataFrame(rows, columns=["as_of", "tenor_years", "par_yield", "row_ref"])


def mfapi_to_benchmark_csv(payload: dict | str, fund_code: str) -> str:
    """Convert an mfapi.in NAV history (Indian mutual funds) to our benchmark CSV.

    Uses month-end NAVs; the monthly return is NAV_t / NAV_{t-1} - 1. Used by
    ``python -m app.ingestion.fetch mfapi <scheme_code> <fund_code>`` to plug a
    real fund's history in as a benchmark or a mandate proxy.
    """
    data = json.loads(payload) if isinstance(payload, str) else payload
    navs = pd.DataFrame(data["data"])
    navs["date"] = pd.to_datetime(navs["date"], format="%d-%m-%Y")
    navs["nav"] = pd.to_numeric(navs["nav"], errors="coerce")
    navs = navs.dropna().sort_values("date")
    monthly = navs.groupby(navs["date"].dt.to_period("M"))["nav"].last()
    rets = monthly.pct_change().dropna()
    lines = ["fund_code,month_end,return_pct"]
    for period, r in rets.items():
        lines.append(f"{fund_code},{period.to_timestamp(how='end').date()},{r * 100:.6f}")
    return "\n".join(lines) + "\n"


ADAPTERS: dict[str, Adapter] = {
    a.name: a
    for a in (
        CustodianCsvAdapter(),
        ManagerExcelAdapter(),
        BenchmarkCsvAdapter(),
        LiabilityCsvAdapter(),
        CurveCsvAdapter(),
        TreasuryParYieldAdapter(),
    )
}
