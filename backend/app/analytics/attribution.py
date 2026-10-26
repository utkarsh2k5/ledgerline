"""Performance attribution: *why* did the fund beat or lag its benchmark?

Single period: Brinson-Fachler
------------------------------
For each segment i (asset class) with portfolio weight wp, benchmark weight wb,
portfolio return rp, benchmark return rb, and total benchmark return B:

    allocation_i  = (wp_i - wb_i) * (rb_i - B)      # over/underweighting good segments
    selection_i   = wb_i * (rp_i - rb_i)            # managers beating their own benchmarks
    interaction_i = (wp_i - wb_i) * (rp_i - rb_i)   # both at once

and  sum_i (allocation + selection + interaction) == R - B  exactly, where
R = sum wp*rp and B = sum wb*rb.

Multi-period linking
--------------------
Monthly effects add up to the *arithmetic* sum of monthly excess returns, but
the client sees *compounded* returns, and  prod(1+R_t) - prod(1+B_t) != sum(R_t - B_t).
Simply adding monthly effects therefore doesn't reconcile to the reported
excess return. Two standard fixes are implemented:

* Carino (1999): scale each month's effects by k_t / k, where
      k_t = ln(1+R_t) - ln(1+B_t)) / (R_t - B_t)   and   k = same for the full period.
* GRAP (Frongello 2002): multiply month t's effects by the compounded portfolio
  return before t and the compounded benchmark return after t.

Both make linked effects sum exactly to  R_total - B_total.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EFFECTS = ("allocation", "selection", "interaction")


def brinson_fachler(wp, wb, rp, rb) -> pd.DataFrame:
    """Single-period attribution. Inputs are aligned 1-D arrays (one entry per segment).

    Weights must each sum to 1 (within 1e-9).
    """
    wp, wb, rp, rb = (np.asarray(x, dtype=float) for x in (wp, wb, rp, rb))
    if not (np.isclose(wp.sum(), 1.0, atol=1e-9) and np.isclose(wb.sum(), 1.0, atol=1e-9)):
        raise ValueError(f"Weights must sum to 1 (portfolio={wp.sum():.10f}, benchmark={wb.sum():.10f})")
    B = float(np.dot(wb, rb))
    return pd.DataFrame(
        {
            "allocation": (wp - wb) * (rb - B),
            "selection": wb * (rp - rb),
            "interaction": (wp - wb) * (rp - rb),
        }
    )


def _k(r: float, b: float) -> float:
    """Carino log-scaling coefficient, with the limit 1/(1+r) when r == b."""
    if np.isclose(r, b, atol=1e-14):
        return 1.0 / (1.0 + r)
    return (np.log1p(r) - np.log1p(b)) / (r - b)


def carino_coefficients(R: np.ndarray, B: np.ndarray) -> np.ndarray:
    R, B = np.asarray(R, dtype=float), np.asarray(B, dtype=float)
    total_r, total_b = np.prod(1 + R) - 1, np.prod(1 + B) - 1
    k = _k(total_r, total_b)
    return np.array([_k(r, b) for r, b in zip(R, B)]) / k


def grap_coefficients(R: np.ndarray, B: np.ndarray) -> np.ndarray:
    R, B = np.asarray(R, dtype=float), np.asarray(B, dtype=float)
    before = np.concatenate([[1.0], np.cumprod(1 + R)[:-1]])          # prod_{s<t} (1+R_s)
    after = np.concatenate([np.cumprod((1 + B)[::-1])[::-1][1:], [1.0]])  # prod_{s>t} (1+B_s)
    return before * after


@dataclass
class AttributionResult:
    segments: pd.DataFrame       # rows: segments; columns: allocation, selection, interaction, total
    monthly: pd.DataFrame        # long: month, segment, effect, raw, linked
    portfolio_return: float      # compounded
    benchmark_return: float      # compounded
    method: str

    @property
    def excess_return(self) -> float:
        return self.portfolio_return - self.benchmark_return

    def totals(self) -> dict[str, float]:
        return {e: float(self.segments[e].sum()) for e in EFFECTS}


def multi_period_attribution(frame: pd.DataFrame, method: str = "carino") -> AttributionResult:
    """Linked attribution over many months.

    ``frame`` is long format with columns: month, segment, wp, wb, rp, rb.
    """
    if method not in {"carino", "grap", "sum"}:
        raise ValueError("method must be carino, grap or sum")
    months = sorted(frame["month"].unique())
    segs = list(dict.fromkeys(frame["segment"]))
    raw_rows, R, B = [], [], []
    for m in months:
        g = frame[frame["month"] == m].set_index("segment").reindex(segs)
        effects = brinson_fachler(g["wp"], g["wb"], g["rp"], g["rb"])
        effects.index = segs
        R.append(float(np.dot(g["wp"], g["rp"])))
        B.append(float(np.dot(g["wb"], g["rb"])))
        for seg in segs:
            for e in EFFECTS:
                raw_rows.append({"month": m, "segment": seg, "effect": e, "raw": float(effects.at[seg, e])})
    R, B = np.array(R), np.array(B)

    if method == "carino":
        coef = carino_coefficients(R, B)
    elif method == "grap":
        coef = grap_coefficients(R, B)
    else:
        coef = np.ones(len(months))  # naive arithmetic sum, kept to show why linking matters
    coef_by_month = dict(zip(months, coef))

    monthly = pd.DataFrame(raw_rows)
    monthly["linked"] = monthly["raw"] * monthly["month"].map(coef_by_month)
    segments = monthly.pivot_table(index="segment", columns="effect", values="linked", aggfunc="sum").reindex(segs)
    segments = segments[list(EFFECTS)]
    segments["total"] = segments.sum(axis=1)
    return AttributionResult(
        segments=segments,
        monthly=monthly,
        portfolio_return=float(np.prod(1 + R) - 1),
        benchmark_return=float(np.prod(1 + B) - 1),
        method=method,
    )
