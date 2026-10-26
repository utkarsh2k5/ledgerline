"""Yield curve bootstrapping.

Government bond yields are quoted as *par yields*: the coupon that makes a
bond price at 100. To discount a single cashflow at year t we need the *zero*
(spot) rate for t, which we strip out of the par curve one year at a time:

    1 = c_n * sum_{i=1..n} DF_i + DF_n            (an n-year par bond prices at par)
=>  DF_n = (1 - c_n * sum_{i<n} DF_i) / (1 + c_n)
    z_n  = DF_n ** (-1/n) - 1

Annual coupons, linear interpolation of par yields between quoted tenors,
flat extrapolation beyond the ends.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DiscountCurve:
    years: np.ndarray       # 1, 2, ..., N
    zero_rates: np.ndarray  # annually compounded

    def discount_factors(self, shift: float = 0.0) -> np.ndarray:
        """Discount factors for each year, with a parallel shift (decimal) to zero rates."""
        return (1.0 + self.zero_rates + shift) ** (-self.years)

    def zero_at(self, year: int) -> float:
        idx = min(max(int(year), 1), len(self.years)) - 1
        return float(self.zero_rates[idx])


def interpolate_par(tenors, par_yields, years: np.ndarray) -> np.ndarray:
    tenors = np.asarray(tenors, dtype=float)
    par_yields = np.asarray(par_yields, dtype=float)
    order = np.argsort(tenors)
    return np.interp(years, tenors[order], par_yields[order])  # flat outside range


def bootstrap(tenors, par_yields, max_year: int = 80) -> DiscountCurve:
    if len(tenors) == 0:
        raise ValueError("Empty curve")
    years = np.arange(1, max_year + 1, dtype=float)
    par = interpolate_par(tenors, par_yields, years)
    dfs = np.empty_like(par)
    running = 0.0
    for i, c in enumerate(par):
        dfs[i] = (1.0 - c * running) / (1.0 + c)
        if dfs[i] <= 0:
            raise ValueError(f"Curve bootstrap failed at year {i + 1}: non-positive discount factor")
        running += dfs[i]
    zeros = dfs ** (-1.0 / years) - 1.0
    return DiscountCurve(years=years, zero_rates=zeros)
