"""Return and risk calculations. Pure functions over numpy/pandas, no I/O."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import brentq


def modified_dietz(begin_mv, end_mv, net_flow, flow_weight: float = 0.5):
    """Monthly return with cash flows assumed to occur mid-period.

        r = (EMV - BMV - CF) / (BMV + w * CF)

    ``flow_weight`` is the fraction of the period the flow was invested for
    (0.5 = mid-month). Works on scalars or arrays/Series.
    """
    begin_mv = np.asarray(begin_mv, dtype=float) if not isinstance(begin_mv, pd.Series) else begin_mv.astype(float)
    end_mv = np.asarray(end_mv, dtype=float) if not isinstance(end_mv, pd.Series) else end_mv.astype(float)
    net_flow = np.asarray(net_flow, dtype=float) if not isinstance(net_flow, pd.Series) else net_flow.astype(float)
    denom = begin_mv + flow_weight * net_flow
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (end_mv - begin_mv - net_flow) / denom
    if isinstance(r, pd.Series):
        return r.where(denom != 0)
    return np.where(denom != 0, r, np.nan)


def chain_link(returns: Sequence[float] | np.ndarray) -> float:
    """Time-weighted return: product of (1 + r_t) minus 1."""
    arr = np.asarray(returns, dtype=float)
    return float(np.prod(1.0 + arr) - 1.0)


def annualise(cumulative: float, months: int) -> float:
    """Geometric annualisation. Periods under a year are NOT annualised (GIPS convention)."""
    if months < 12:
        return cumulative
    return float((1.0 + cumulative) ** (12.0 / months) - 1.0)


def annualised_volatility(returns: Sequence[float]) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return float("nan")
    return float(np.std(arr, ddof=1) * np.sqrt(12))


def tracking_error(port: Sequence[float], bench: Sequence[float]) -> float:
    """Annualised standard deviation of monthly (arithmetic) excess returns."""
    return annualised_volatility(np.asarray(port, dtype=float) - np.asarray(bench, dtype=float))


def sharpe_ratio(returns: Sequence[float], rf_annual: float) -> float:
    arr = np.asarray(returns, dtype=float)
    vol = annualised_volatility(arr)
    if not np.isfinite(vol) or vol == 0:
        return float("nan")
    ann = (1 + chain_link(arr)) ** (12 / len(arr)) - 1  # risk ratios always use annualised figures
    return float((ann - rf_annual) / vol)


def information_ratio(port: Sequence[float], bench: Sequence[float]) -> float:
    port, bench = np.asarray(port, dtype=float), np.asarray(bench, dtype=float)
    te = tracking_error(port, bench)
    if not np.isfinite(te) or te == 0:
        return float("nan")
    n = len(port)
    rp = (1 + chain_link(port)) ** (12 / n) - 1
    rb = (1 + chain_link(bench)) ** (12 / n) - 1
    return float((rp - rb) / te)


def max_drawdown(returns: Sequence[float]) -> float:
    """Largest peak-to-trough fall of the cumulative wealth index (negative number)."""
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(returns, dtype=float))])
    peaks = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peaks - 1.0))


def money_weighted_return(begin_value: float, flows: Sequence[float], end_value: float) -> float:
    """Annualised IRR with monthly cash flows.

    ``flows`` are external flows into the portfolio at the end of each month
    (positive = contribution). Solves:  BMV*(1+i)^n + sum CF_t (1+i)^(n-t) = EMV
    for the monthly rate i, then annualises.
    """
    flows = np.asarray(flows, dtype=float)
    n = len(flows)

    def npv(i: float) -> float:
        growth = (1 + i) ** (n - np.arange(1, n + 1))
        return begin_value * (1 + i) ** n + float(np.sum(flows * growth)) - end_value

    monthly = brentq(npv, -0.5, 1.0, maxiter=500)
    return float((1 + monthly) ** 12 - 1)


PERIODS = {"3m": 3, "ytd": None, "1y": 12, "3y": 36}


def period_months(period: str, end_month: pd.Timestamp, available: int) -> int | None:
    """Number of months in a reporting period, or None if history is too short."""
    if period == "ytd":
        n = int(end_month.month)
    elif period == "si":
        n = available
    else:
        n = PERIODS[period]
    return n if n <= available else None
