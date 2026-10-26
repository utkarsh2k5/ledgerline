"""Liability valuation, funding position, hedging and stress tests.

A DB scheme has promised pensions: a stream of future benefit cashflows. Their
value today (present value) moves with interest rates; when rates fall,
liabilities rise. The *funding ratio* = assets / liabilities is what trustees
watch, and the *hedge ratio* says how much of the liabilities' rate
sensitivity the assets offset.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .curve import DiscountCurve

BP = 0.0001


def present_value(cashflows: np.ndarray, curve: DiscountCurve, shift: float = 0.0) -> float:
    """PV of annual cashflows paid at the end of years 1..N."""
    cf = np.asarray(cashflows, dtype=float)
    dfs = curve.discount_factors(shift)
    if len(cf) > len(dfs):
        raise ValueError(f"Cashflows run to year {len(cf)} but curve only to {len(dfs)}")
    return float(np.dot(cf, dfs[: len(cf)]))


def pv01(cashflows: np.ndarray, curve: DiscountCurve) -> float:
    """Change in PV for a 1bp move in rates (positive for liabilities).

    Central difference on purpose: the one-sided version includes a bit of convexity,
    so a scheme hedged with assets of exactly the liability duration showed 99.9%
    instead of 100%.
    """
    return (present_value(cashflows, curve, -BP) - present_value(cashflows, curve, BP)) / 2


def effective_duration(cashflows: np.ndarray, curve: DiscountCurve) -> float:
    up, down = present_value(cashflows, curve, BP), present_value(cashflows, curve, -BP)
    base = present_value(cashflows, curve)
    return float((down - up) / (2 * base * BP))


@dataclass
class FundingPosition:
    assets: float
    liabilities: float
    funding_ratio: float
    surplus: float
    liability_duration: float
    liability_pv01: float
    asset_pv01: float
    hedge_ratio: float


def funding_position(asset_values: np.ndarray, asset_durations: np.ndarray,
                     cashflows: np.ndarray, curve: DiscountCurve) -> FundingPosition:
    assets = float(np.sum(asset_values))
    liabs = present_value(cashflows, curve)
    asset_pv01 = float(np.sum(np.asarray(asset_values) * np.asarray(asset_durations)) * BP)
    liab_pv01 = pv01(cashflows, curve)
    return FundingPosition(
        assets=assets,
        liabilities=liabs,
        funding_ratio=assets / liabs,
        surplus=assets - liabs,
        liability_duration=effective_duration(cashflows, curve),
        liability_pv01=liab_pv01,
        asset_pv01=asset_pv01,
        hedge_ratio=asset_pv01 / liab_pv01,
    )


DEFAULT_SCENARIOS = {
    "Rates -100bp": {"rates_bps": -100, "equity": 0.0},
    "Rates +100bp": {"rates_bps": 100, "equity": 0.0},
    "Equities -20%": {"rates_bps": 0, "equity": -0.20},
    "Equities -20% & rates -50bp": {"rates_bps": -50, "equity": -0.20},
}


def stress_test(asset_values: np.ndarray, asset_durations: np.ndarray, is_growth: np.ndarray,
                cashflows: np.ndarray, curve: DiscountCurve,
                scenarios: dict[str, dict] | None = None) -> list[dict]:
    """Instantaneous shocks. Liabilities are fully revalued on the shifted curve;
    rate-sensitive assets move by -duration * shift (first order); growth assets
    take the equity shock."""
    scenarios = scenarios or DEFAULT_SCENARIOS
    values = np.asarray(asset_values, dtype=float)
    durations = np.asarray(asset_durations, dtype=float)
    growth = np.asarray(is_growth, dtype=bool)
    base = funding_position(values, durations, cashflows, curve)
    out = []
    for name, sc in scenarios.items():
        shift = sc.get("rates_bps", 0) * BP
        shocked = values * (1 - durations * shift)
        shocked = np.where(growth, shocked * (1 + sc.get("equity", 0.0)), shocked)
        liabs = present_value(cashflows, curve, shift)
        fr = float(shocked.sum() / liabs)
        out.append({
            "scenario": name,
            "rates_bps": sc.get("rates_bps", 0),
            "equity": sc.get("equity", 0.0),
            "assets": float(shocked.sum()),
            "liabilities": liabs,
            "funding_ratio": fr,
            "change_in_funding_ratio": fr - base.funding_ratio,
            "change_in_surplus": float(shocked.sum() - liabs) - base.surplus,
        })
    return out
