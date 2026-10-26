"""Builds the full set of facts for a scheme as at a period end.

This is the single source of numbers for reports, the dashboard API and the
AI fact-checker: they all read from the same ``FactBook``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..config import settings
from ..data_access import funds_frame, latest_benchmarks, latest_curve, latest_liabilities, latest_version_ids
from ..funding.curve import bootstrap
from ..funding.liabilities import funding_position, stress_test
from ..funding.simulation import SimParams, simulate_funding_ratio
from ..models import Scheme
from ..recon.engine import golden_returns, open_breaks
from . import returns as R
from .attribution import EFFECTS, AttributionResult, multi_period_attribution
from .facts import FactBook, fmt

PERIOD_LABELS = {"3m": "3 months", "ytd": "Year to date", "1y": "1 year", "3y": "3 years (p.a.)"}


class AnalyticsError(Exception):
    pass


@dataclass
class Analysis:
    scheme: Scheme
    period_end: date
    facts: FactBook
    funds: pd.DataFrame
    months: list[date]
    periods: dict[str, int]                       # available period -> months
    cumulative: pd.DataFrame                      # month, portfolio, benchmark (growth of 1)
    attribution: dict[str, AttributionResult] = field(default_factory=dict)
    funding: dict | None = None                   # position, stress, simulation
    data_versions: dict = field(default_factory=dict)
    attribution_input: pd.DataFrame | None = None  # month, segment, wp, wb, rp, rb

    def fund_codes(self) -> list[str]:
        return list(self.funds["fund_code"])


def _mkey(m: date) -> str:
    return f"{m.year:04d}-{m.month:02d}"


def build_analysis(db: Session, scheme: Scheme, period_end: date, attribution_periods=("3m", "1y", "3y"),
                   linking: str = "carino", with_simulation: bool = True) -> Analysis:
    currency = scheme.currency
    book = FactBook(currency)
    funds = funds_frame(db, scheme.id)
    if funds.empty:
        raise AnalyticsError("Scheme has no funds configured")
    code_of = dict(zip(funds["fund_id"], funds["fund_code"]))

    golden = golden_returns(db, scheme)
    bench = latest_benchmarks(db, scheme.id)
    if golden.empty:
        raise AnalyticsError("No custodian/manager data loaded yet")
    golden = golden[golden["month"] <= period_end]
    bench = bench[bench["month"] <= period_end]
    months = sorted(golden["month"].unique())
    if not months or months[-1] != period_end:
        raise AnalyticsError(f"No data for period end {period_end}; latest month is {months[-1] if months else 'none'}")

    unresolved = golden[golden["ret"].isna()]
    if not unresolved.empty:
        r = unresolved.iloc[0]
        raise AnalyticsError(f"Unresolved missing return for {code_of[r.fund_id]} {r.month}; resolve the break first")

    data = golden.merge(bench[["fund_id", "month", "bench_ret", "bench_row_ref", "bench_version_id"]],
                        on=["fund_id", "month"], how="left")
    missing_bench = data[data["bench_ret"].isna()]
    if not missing_bench.empty:
        r = missing_bench.iloc[0]
        raise AnalyticsError(f"Missing benchmark return for {code_of[r.fund_id]} {r.month}")
    data["fund_code"] = data["fund_id"].map(code_of)

    # Portfolio weights from beginning-of-month market values; fall back to the
    # previous month's closing value if the opening value is missing.
    data = data.sort_values(["fund_id", "month"])
    data["bmv"] = data["begin_mv"].fillna(data.groupby("fund_id")["end_mv"].shift(1)).fillna(0.0)

    target = dict(zip(funds["fund_code"], funds["target_weight"]))
    tw_sum = sum(target.values())
    if not np.isclose(tw_sum, 1.0, atol=1e-6):
        raise AnalyticsError(f"Target weights sum to {tw_sum:.4f}, not 1")

    # leaf facts
    for code, f in funds.set_index("fund_code").iterrows():
        book.add(f"wb.{code}", f"{f.fund_name}: strategic (benchmark) weight", target[code], "pct",
                 "Scheme strategic asset allocation (policy benchmark weight)",
                 sources=[f"scheme_config:{scheme.code}:{code}.target_weight"])

    attr_rows = []
    for m in months:
        mk = _mkey(m)
        month_rows = data[data["month"] == m]
        total_bmv = float(month_rows["bmv"].sum())
        if total_bmv <= 0:
            raise AnalyticsError(f"Total opening market value is zero in {mk}")
        for r in month_rows.itertuples(index=False):
            code = r.fund_code
            if r.origin == "custodian":
                formula = (f"Modified Dietz: (EMV {r.end_mv:,.0f} - BMV {r.begin_mv:,.0f} - CF {r.net_flow:,.0f})"
                           f" / (BMV + 0.5 x CF)")
            elif r.origin == "override":
                formula = "Manual override recorded on reconciliation break"
            elif r.origin == "manager":
                formula = "Manager-reported return accepted on reconciliation break"
            else:
                formula = "Custodian return accepted on reconciliation break"
            book.add(f"ret.{code}.{mk}", f"{code} return {mk}", r.ret, "pct", formula, sources=r.row_refs)
            book.add(f"bench.{code}.{mk}", f"{code} benchmark return {mk}", r.bench_ret, "pct",
                     "Benchmark index return from provider file", sources=[r.bench_row_ref])
            book.add(f"wp.{code}.{mk}", f"{code} portfolio weight {mk}", r.bmv / total_bmv, "pct",
                     f"Opening market value {r.bmv:,.0f} / total opening market value {total_bmv:,.0f}",
                     sources=[x for x in r.row_refs if "#row" in x or "!" in x][:1])
            attr_rows.append({"month": m, "segment": code, "wp": r.bmv / total_bmv, "wb": target[code],
                              "rp": r.ret, "rb": r.bench_ret})
        codes = list(month_rows["fund_code"])
        # Total = sum of weight x mandate return. This ignores intra-month flow timing at the
        # total level (a Modified Dietz on aggregated values would differ by a few bps), but
        # it's what makes the attribution effects add up to exactly fund - benchmark.
        tot = sum(book.value(f"wp.{c}.{mk}") * book.value(f"ret.{c}.{mk}") for c in codes)
        btot = sum(book.value(f"wb.{c}") * book.value(f"bench.{c}.{mk}") for c in codes)
        book.add(f"ret.TOTAL.{mk}", f"Total fund return {mk}", tot, "pct",
                 "Sum over mandates of portfolio weight x mandate return",
                 inputs=[f"wp.{c}.{mk}" for c in codes] + [f"ret.{c}.{mk}" for c in codes])
        book.add(f"bench.TOTAL.{mk}", f"Total benchmark return {mk}", btot, "pct",
                 "Sum over mandates of strategic weight x benchmark return",
                 inputs=[f"wb.{c}" for c in codes] + [f"bench.{c}.{mk}" for c in codes])

    # period returns
    end_ts = pd.Timestamp(period_end)
    periods: dict[str, int] = {}
    for p in ("3m", "ytd", "1y", "3y"):
        n = R.period_months(p, end_ts, len(months))
        if n:
            periods[p] = n
    names = dict(zip(funds["fund_code"], funds["fund_name"]))
    names["TOTAL"] = "Total fund"
    for code in [*funds["fund_code"], "TOTAL"]:
        for p, n in periods.items():
            window = [_mkey(m) for m in months[-n:]]
            rets = [book.value(f"ret.{code}.{k}") for k in window]
            bens = [book.value(f"bench.{code}.{k}") for k in window]
            ann = n >= 12
            how = f"Chain-linked over {n} months: prod(1 + r_t) - 1" + (f", annualised: (1 + R)^(12/{n}) - 1" if ann and n > 12 else "")
            rp = R.annualise(R.chain_link(rets), n)
            rb = R.annualise(R.chain_link(bens), n)
            fid = f"perf.{code}.{p}"
            book.add(f"{fid}.ret", f"{names[code]} return, {PERIOD_LABELS[p]}", rp, "pct", how,
                     inputs=[f"ret.{code}.{k}" for k in window])
            book.add(f"{fid}.bench", f"{names[code]} benchmark return, {PERIOD_LABELS[p]}", rb, "pct", how,
                     inputs=[f"bench.{code}.{k}" for k in window])
            book.add(f"{fid}.excess", f"{names[code]} excess return, {PERIOD_LABELS[p]}", rp - rb, "pct",
                     "Fund return - benchmark return (arithmetic difference)",
                     inputs=[f"{fid}.ret", f"{fid}.bench"])

        # risk (longest window, at least 12 months)
        risk_p = "3y" if "3y" in periods else ("1y" if "1y" in periods else None)
        if risk_p:
            n = periods[risk_p]
            window = [_mkey(m) for m in months[-n:]]
            rets = [book.value(f"ret.{code}.{k}") for k in window]
            bens = [book.value(f"bench.{code}.{k}") for k in window]
            ins = [f"ret.{code}.{k}" for k in window]
            bins = [f"bench.{code}.{k}" for k in window]
            rk = f"risk.{code}.{risk_p}"
            book.add(f"{rk}.vol", f"{names[code]} volatility ({risk_p}, annualised)", R.annualised_volatility(rets), "pct",
                     "Sample std. dev. of monthly returns x sqrt(12)", inputs=ins)
            book.add(f"{rk}.te", f"{names[code]} tracking error ({risk_p})", R.tracking_error(rets, bens), "pct",
                     "Std. dev. of monthly (fund - benchmark) x sqrt(12)", inputs=ins + bins)
            book.add(f"{rk}.ir", f"{names[code]} information ratio ({risk_p})", R.information_ratio(rets, bens), "ratio",
                     "Annualised excess return / tracking error", inputs=ins + bins)
            book.add(f"{rk}.sharpe", f"{names[code]} Sharpe ratio ({risk_p})", R.sharpe_ratio(rets, settings.risk_free_annual),
                     "ratio", f"(Annualised return - risk-free {settings.risk_free_annual:.1%}) / volatility", inputs=ins)
            book.add(f"{rk}.maxdd", f"{names[code]} maximum drawdown ({risk_p})", R.max_drawdown(rets), "pct",
                     "Largest peak-to-trough fall in cumulative value", inputs=ins)

    # market values & allocation
    last = data[data["month"] == period_end]
    total_mv = float(last["end_mv"].sum())
    for r in last.itertuples(index=False):
        book.add(f"mv.{r.fund_code}.end", f"{r.fund_code} market value at {period_end}", r.end_mv, "money",
                 "Custodian closing market value", sources=[x for x in r.row_refs if "custodian" in x.lower()][:1] or r.row_refs[:1])
    book.add("mv.TOTAL.end", f"Total market value at {period_end}", total_mv, "money", "Sum of mandate closing values",
             inputs=[f"mv.{c}.end" for c in last["fund_code"]])
    for c in last["fund_code"]:
        book.add(f"alloc.{c}.actual", f"{c} actual allocation", book.value(f"mv.{c}.end") / total_mv, "pct",
                 "Mandate value / total value", inputs=[f"mv.{c}.end", "mv.TOTAL.end"])
        book.add(f"alloc.{c}.deviation", f"{c} allocation vs target", book.value(f"alloc.{c}.actual") - target[c], "pct",
                 "Actual allocation - strategic weight", inputs=[f"alloc.{c}.actual", f"wb.{c}"])
    for p, n in periods.items():
        flow_rows = data[data["month"].isin(months[-n:])]
        book.add(f"flows.TOTAL.{p}", f"Net cash flow, {PERIOD_LABELS[p]}", float(flow_rows["net_flow"].fillna(0).sum()),
                 "money", "Sum of custodian net cash flows (contributions - benefits paid)",
                 sources=[f"custodian rows for {len(flow_rows)} fund-months"])

    # cumulative performance series
    cum_rows, wp_, wb_ = [], 1.0, 1.0
    for m in months:
        mk = _mkey(m)
        wp_ *= 1 + book.value(f"ret.TOTAL.{mk}")
        wb_ *= 1 + book.value(f"bench.TOTAL.{mk}")
        cum_rows.append({"month": m, "portfolio": wp_, "benchmark": wb_})
    cumulative = pd.DataFrame(cum_rows)

    # attribution
    attr_df = pd.DataFrame(attr_rows)
    attributions: dict[str, AttributionResult] = {}
    for p in attribution_periods:
        if p not in periods:
            continue
        n = periods[p]
        window_months = months[-n:]
        res = multi_period_attribution(attr_df[attr_df["month"].isin(window_months)], method=linking)
        attributions[p] = res
        wkeys = [_mkey(m) for m in window_months]
        for code in res.segments.index:
            ins = [f"ret.{code}.{k}" for k in wkeys] + [f"bench.{code}.{k}" for k in wkeys] + [f"wp.{code}.{k}" for k in wkeys] + [f"wb.{code}"]
            for e in (*EFFECTS, "total"):
                book.add(f"attr.{p}.{code}.{e}", f"{code} {e} effect, {PERIOD_LABELS[p]}",
                         float(res.segments.at[code, e]), "pct",
                         _attr_formula(e, linking), inputs=ins if e != "total" else
                         [f"attr.{p}.{code}.{x}" for x in EFFECTS])
        for e in EFFECTS:
            book.add(f"attr.{p}.TOTAL.{e}", f"Total {e} effect, {PERIOD_LABELS[p]}", float(res.segments[e].sum()), "pct",
                     f"Sum of mandate {e} effects", inputs=[f"attr.{p}.{c}.{e}" for c in res.segments.index])
        book.add(f"attr.{p}.TOTAL.total", f"Total active return explained, {PERIOD_LABELS[p]}",
                 float(res.segments["total"].sum()), "pct",
                 "Allocation + selection + interaction; equals compounded fund return - compounded benchmark return",
                 inputs=[f"attr.{p}.TOTAL.{e}" for e in EFFECTS])

    # reconciliation status
    ob = open_breaks(db, scheme.id)
    book.add("recon.open_material", "Open material reconciliation breaks", sum(b.severity == "material" for b in ob), "count",
             "Count of unresolved breaks above the materiality threshold", sources=["recon_breaks"])
    book.add("recon.open_minor", "Open minor reconciliation breaks", sum(b.severity == "minor" for b in ob), "count",
             "Count of unresolved breaks within the materiality threshold", sources=["recon_breaks"])
    book.add("recon.overrides", "Reconciled values used in this period",
             int((golden["origin"].isin(["manager", "override"])).sum()), "count",
             "Fund-months where a resolved break replaced the custodian return", sources=["recon_breaks"])

    analysis = Analysis(scheme=scheme, period_end=period_end, facts=book, funds=funds, months=months,
                        periods=periods, cumulative=cumulative, attribution=attributions,
                        attribution_input=attr_df)

    # funding
    analysis.funding = _funding(db, scheme, book, funds, last, with_simulation)

    analysis.data_versions = latest_version_ids(db, scheme.id)
    return analysis


def _attr_formula(effect: str, linking: str) -> str:
    base = {
        "allocation": "Brinson-Fachler allocation: (wp - wb) x (rb - B)",
        "selection": "Brinson-Fachler selection: wb x (rp - rb)",
        "interaction": "Brinson-Fachler interaction: (wp - wb) x (rp - rb)",
        "total": "Allocation + selection + interaction",
    }[effect]
    if effect == "total":
        return base
    link = {"carino": "Carino log-linked across months", "grap": "GRAP-linked across months",
            "sum": "summed across months (unlinked)"}[linking]
    return f"{base}; monthly effects {link}"


def _funding(db: Session, scheme: Scheme, book: FactBook, funds: pd.DataFrame, last: pd.DataFrame,
             with_simulation: bool) -> dict | None:
    liabs, liab_vid = latest_liabilities(db, scheme.id)
    curve_df, curve_vid = latest_curve(db, scheme.id)
    if liabs.empty or curve_df.empty:
        return None
    curve = bootstrap(curve_df["tenor_years"], curve_df["par_yield"], max_year=max(80, int(liabs["year"].max())))
    cf = np.zeros(int(liabs["year"].max()))
    cf[liabs["year"].to_numpy() - 1] = liabs["amount"].to_numpy()
    meta = funds.set_index("fund_code")
    values = last.set_index("fund_code")["end_mv"].reindex(meta.index).fillna(0).to_numpy()
    durations = meta["effective_duration"].to_numpy()
    growth = meta["is_growth"].to_numpy()
    pos = funding_position(values, durations, cf, curve)

    liab_src = [f"{liabs['row_ref'].iloc[0].split('#')[0]} ({len(liabs)} annual cashflows, dataset v{liab_vid})"]
    curve_src = [f"{curve_df['row_ref'].iloc[0].split('#')[0]} (as of {curve_df['as_of'].iloc[0]}, dataset v{curve_vid})"]
    book.add("funding.liabilities", "Value of liabilities (PV of projected benefits)", pos.liabilities, "money",
             "Sum of cashflow_t x discount factor_t, zero curve bootstrapped from government par yields",
             sources=liab_src + curve_src)
    book.add("funding.assets", "Scheme assets", pos.assets, "money", "Total market value", inputs=["mv.TOTAL.end"])
    book.add("funding.ratio", "Funding ratio", pos.funding_ratio, "pct", "Assets / liabilities",
             inputs=["funding.assets", "funding.liabilities"])
    book.add("funding.surplus", "Surplus / (deficit)", pos.surplus, "money", "Assets - liabilities",
             inputs=["funding.assets", "funding.liabilities"])
    book.add("funding.liab_duration", "Liability duration", pos.liability_duration, "years",
             "Effective duration: (PV(-1bp) - PV(+1bp)) / (2 x PV x 0.0001)", inputs=["funding.liabilities"])
    book.add("funding.liab_pv01", "Liability PV01", pos.liability_pv01, "money",
             "Rise in liability value for a 1bp fall in rates", inputs=["funding.liabilities"])
    mv_ids = [f"mv.{c}.end" for c in meta.index if f"mv.{c}.end" in book]
    book.add("funding.asset_pv01", "Asset PV01 (interest-rate hedge)", pos.asset_pv01, "money",
             "Sum of mandate value x effective duration x 0.0001", inputs=mv_ids,
             sources=[f"scheme_config:{scheme.code}:effective_duration"])
    book.add("funding.hedge_ratio", "Interest-rate hedge ratio", pos.hedge_ratio, "pct", "Asset PV01 / liability PV01",
             inputs=["funding.asset_pv01", "funding.liab_pv01"])

    stresses = stress_test(values, durations, growth, cf, curve)
    for i, s in enumerate(stresses):
        sid = f"funding.stress.{i}"
        book.add(f"{sid}.ratio", f"Funding ratio after: {s['scenario']}", s["funding_ratio"], "pct",
                 f"Instantaneous shock: rates {s['rates_bps']:+d}bp, growth assets {s['equity']:+.0%}; liabilities revalued on shifted curve",
                 inputs=["funding.ratio", "funding.liabilities"])
        book.add(f"{sid}.change", f"Change in funding ratio: {s['scenario']}", s["change_in_funding_ratio"], "pct",
                 "Stressed funding ratio - current funding ratio", inputs=[f"{sid}.ratio", "funding.ratio"])

    sim = None
    if with_simulation:
        matching_value = float(values[~growth].sum())
        matching_dur = float((values[~growth] * durations[~growth]).sum() / matching_value) if matching_value else 0.0
        base_yield = curve.zero_at(round(pos.liability_duration))
        sim = simulate_funding_ratio(
            growth_assets=float(values[growth].sum()), matching_assets=matching_value,
            matching_duration=matching_dur, liabilities=pos.liabilities,
            liability_duration=pos.liability_duration, base_yield=base_yield, benefit_payments=cf[:10],
            # sponsor pays the deficit off over 10 years (a typical recovery plan)
            params=SimParams(sponsor_contribution=max(0.0, -pos.surplus) / 10),
        )
        book.add("funding.sim.median_10y", "Median projected funding ratio in 10 years", sim["median_end"], "pct",
                 f"Monte Carlo, {sim['n_paths']:,} paths, seed {sim['seed']}; deficit contributions over 10 years", inputs=["funding.ratio", "funding.hedge_ratio"])
        book.add("funding.sim.prob_full_10y", "Probability of being fully funded in 10 years",
                 sim["prob_fully_funded_end"], "pct", "Share of simulated paths with funding ratio >= 100% at year 10",
                 inputs=["funding.sim.median_10y"])

    return {"position": pos.__dict__, "stress": stresses, "simulation": sim,
            "curve": {"years": curve.years[:50].tolist(), "zero_rates": curve.zero_rates[:50].tolist(),
                      "par_tenors": curve_df["tenor_years"].tolist(), "par_yields": curve_df["par_yield"].tolist(),
                      "as_of": str(curve_df["as_of"].iloc[0])},
            "cashflows": cf[:60].tolist()}


def describe(book: FactBook, fact_id: str) -> str:
    f = book[fact_id]
    return fmt(f.value, f.unit, book.currency)
