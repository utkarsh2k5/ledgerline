"""Monte Carlo projection of the funding ratio (fully vectorised with NumPy).

Model (annual steps, deliberately simple and documented):

* Interest-rate level shift x_t follows Vasicek mean reversion:
      x_{t+1} = x_t + a (theta - x_t) + sigma_r * e1
* Growth assets earn  mu_e + sigma_e * e2,  with corr(e1, e2) = rho.
* Matching assets and liabilities both accrue at the current yield (y0 + x_t)
  and revalue by  -duration * dx  (first-order duration approximation).
* Each year benefits are paid out of assets and reduce liabilities, and the
  sponsor pays a fixed deficit contribution into growth assets.

This is an illustration of the mechanics (how hedging narrows the range of
outcomes), not an actuarial valuation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SimParams:
    years: int = 10
    n_paths: int = 10_000
    seed: int = 20261026
    mu_equity: float = 0.06
    sigma_equity: float = 0.13
    rate_mean_reversion: float = 0.15
    rate_long_run_shift: float = 0.0
    sigma_rate: float = 0.0075
    rho: float = 0.25
    sponsor_contribution: float = 0.0  # per year, currency units
    percentiles: tuple[int, ...] = field(default=(5, 25, 50, 75, 95))


def simulate_funding_ratio(growth_assets: float, matching_assets: float, matching_duration: float,
                           liabilities: float, liability_duration: float, base_yield: float,
                           benefit_payments: np.ndarray, params: SimParams | None = None) -> dict:
    p = params or SimParams()
    rng = np.random.default_rng(p.seed)
    n, T = p.n_paths, p.years
    e1 = rng.standard_normal((T, n))
    e2 = p.rho * e1 + np.sqrt(1 - p.rho ** 2) * rng.standard_normal((T, n))

    G = np.full(n, float(growth_assets))
    M = np.full(n, float(matching_assets))
    L = np.full(n, float(liabilities))
    x = np.zeros(n)
    payments = np.zeros(T)
    payments[: min(T, len(benefit_payments))] = np.asarray(benefit_payments, dtype=float)[:T]

    ratios = np.empty((T + 1, n))
    ratios[0] = (G + M) / L
    for t in range(T):
        y = base_yield + x
        x_next = x + p.rate_mean_reversion * (p.rate_long_run_shift - x) + p.sigma_rate * e1[t]
        dx = x_next - x
        G = G * (1 + p.mu_equity + p.sigma_equity * e2[t])
        M = M * (1 + y) * (1 - matching_duration * dx)
        L = L * (1 + y) * (1 - liability_duration * dx)
        # pay benefits pro rata from assets, contributions into growth
        A = G + M
        share_g = np.divide(G, A, out=np.full(n, 0.5), where=A > 0)
        G = G - payments[t] * share_g + p.sponsor_contribution
        M = M - payments[t] * (1 - share_g)
        L = np.maximum(L - payments[t], 1e-9)
        x = x_next
        ratios[t + 1] = (G + M) / L

    pct = np.percentile(ratios, p.percentiles, axis=1)
    return {
        "years": list(range(T + 1)),
        "percentiles": {str(q): pct[i].tolist() for i, q in enumerate(p.percentiles)},
        "prob_fully_funded_end": float(np.mean(ratios[-1] >= 1.0)),
        "prob_below_80_end": float(np.mean(ratios[-1] < 0.8)),
        "median_end": float(np.median(ratios[-1])),
        "n_paths": n,
        "seed": p.seed,
    }
