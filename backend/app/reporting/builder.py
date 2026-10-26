"""Spec + facts -> format-neutral report document (IR)."""
from __future__ import annotations

from ..analytics.engine import PERIOD_LABELS, Analysis
from ..analytics.facts import fmt
from .ir import KPI, Callout, Cell, Chart, Commentary, Document, KPIGrid, Paragraph, Section, Table
from .spec import ReportSpec, SectionSpec

SHORT = {"3m": "Quarter", "ytd": "YTD", "1y": "1 year", "3y": "3 years p.a."}


class BuildError(Exception):
    pass


def build_document(analysis: Analysis, spec: ReportSpec, commentary: Commentary | None,
                   breaks: list[dict], gate_note: str | None = None) -> Document:
    b = analysis.facts
    sections: list[Section] = []
    if gate_note:
        sections.append(Section("Important notice", [Callout(gate_note, "warn")]))
    for s in spec.sections:
        handler = _HANDLERS[s.type]
        section = handler(analysis, s, commentary=commentary, breaks=breaks)
        if section is not None:
            sections.append(section)

    doc = Document(
        title=spec.title,
        subtitle=f"Quarter to {analysis.period_end:%d %B %Y}",
        scheme_name=analysis.scheme.name,
        period_label=f"{analysis.period_end:%B %Y}",
        prepared_for=spec.audience,
        sections=sections,
        meta={"spec": spec.name, "currency": b.currency},
    )
    unknown = [f for f in doc.fact_ids() if f not in b]
    if unknown:
        raise BuildError(f"Spec references unknown facts: {unknown[:5]}")
    return doc


# --- helpers -------------------------------------------------------------------

def _cell(analysis: Analysis, fid: str, signed: bool = False, tone: bool = False, bold: bool = False) -> Cell:
    b = analysis.facts
    if fid not in b:
        return Cell("–")
    f = b[fid]
    text = fmt(f.value, f.unit, b.currency)
    if signed and f.value > 0:
        text = "+" + text
    t = "neutral"
    if tone:
        t = "good" if f.value > 0.00005 else ("bad" if f.value < -0.00005 else "neutral")
    return Cell(text, fid, t, bold)


def _names(analysis: Analysis) -> dict[str, str]:
    return dict(zip(analysis.funds["fund_code"], analysis.funds["fund_name"]))


# --- section handlers -------------------------------------------------------------

def _kpis(analysis: Analysis, s: SectionSpec, **_) -> Section:
    b = analysis.facts
    items = []
    for it in s.items:
        if it.fact not in b:
            raise BuildError(f"KPI fact '{it.fact}' not available")
        f = b[it.fact]
        sub, tone = None, "neutral"
        if it.sub and it.sub in b:
            sf = b[it.sub]
            if ".excess" in it.sub:
                sub = ("+" if sf.value > 0 else "") + fmt(sf.value, sf.unit, b.currency) + " vs benchmark"
            elif it.sub == "funding.surplus":
                sub = f"{fmt(abs(sf.value), 'money', b.currency)} {'surplus' if sf.value >= 0 else 'deficit'}"
            else:
                sub = fmt(sf.value, sf.unit, b.currency)
            tone = "good" if sf.value > 0 else "bad"
        items.append(KPI(it.label or f.label, fmt(f.value, f.unit, b.currency), f.id, sub, tone,
                         it.sub if it.sub in b else None))
    return Section(s.title or "At a glance", [KPIGrid(items)])


def _commentary(analysis: Analysis, s: SectionSpec, commentary: Commentary | None = None, **_) -> Section | None:
    if commentary is None:
        return None
    return Section(s.title or "Commentary", [commentary])


def _performance(analysis: Analysis, s: SectionSpec, **_) -> Section:
    periods = [p for p in s.periods if p in analysis.periods]
    names = _names(analysis)
    cols = ["Mandate", "Value"]
    for p in periods:
        cols += [f"{SHORT[p]}", "vs bmk"]
    rows = []
    for code in [*analysis.fund_codes(), "TOTAL"]:
        is_total = code == "TOTAL"
        row = [Cell("Total fund" if is_total else names[code], align="left", bold=is_total),
               _cell(analysis, f"mv.{code}.end", bold=is_total)]
        for p in periods:
            row.append(_cell(analysis, f"perf.{code}.{p}.ret", bold=is_total))
            row.append(_cell(analysis, f"perf.{code}.{p}.excess", signed=True, tone=True, bold=is_total))
        rows.append(row)
    bench_rows = []
    for code in [*analysis.fund_codes(), "TOTAL"]:
        bench_rows.append([Cell("Total benchmark" if code == "TOTAL" else analysis.funds.set_index("fund_code").at[code, "benchmark_name"], align="left")]
                          + [_cell(analysis, f"perf.{code}.{p}.bench") for p in periods])
    return Section(s.title or "Performance", [
        Table(cols, rows, note="Returns are time-weighted (Modified Dietz monthly, chain-linked); periods over one year "
                               "are annualised. 'vs bmk' = fund return minus benchmark return."),
        Table(["Benchmark"] + [SHORT[p] for p in periods], bench_rows, caption="Benchmark returns"),
    ])


def _chart(analysis: Analysis, s: SectionSpec, **_) -> Section:
    if s.chart == "cumulative":
        data = {"months": [f"{m:%b %y}" for m in analysis.cumulative["month"]],
                "portfolio": analysis.cumulative["portfolio"].round(8).tolist(),
                "benchmark": analysis.cumulative["benchmark"].round(8).tolist()}
        return Section(s.title or "Cumulative performance",
                       [Chart("cumulative", s.title or "Cumulative performance", data,
                              caption="Growth of the total fund vs its strategic benchmark, cumulative since start of data.")])
    return _allocation(analysis, s)


def _allocation(analysis: Analysis, s: SectionSpec, **_) -> Section:
    names = _names(analysis)
    b = analysis.facts
    codes = analysis.fund_codes()
    data = {"segments": codes,
            "actual": {c: round(b.value(f"alloc.{c}.actual"), 8) for c in codes},
            "target": {c: round(b.value(f"wb.{c}"), 8) for c in codes}}
    rows = [[Cell(names[c], align="left"), _cell(analysis, f"mv.{c}.end"), _cell(analysis, f"alloc.{c}.actual"),
             _cell(analysis, f"wb.{c}"), _cell(analysis, f"alloc.{c}.deviation", signed=True)] for c in codes]
    rows.append([Cell("Total fund", align="left", bold=True), _cell(analysis, "mv.TOTAL.end", bold=True),
                 Cell("100.00%", bold=True), Cell("100.00%", bold=True), Cell("")])
    return Section(s.title or "Asset allocation", [
        Chart("allocation", "Actual vs strategic allocation", data),
        Table(["Mandate", "Value", "Actual", "Target", "Deviation"], rows),
    ])


def _attribution(analysis: Analysis, s: SectionSpec, **_) -> Section | None:
    p = s.period
    res = analysis.attribution.get(p)
    if res is None:
        return None
    names = _names(analysis)
    b = analysis.facts
    effects = ["allocation", "selection", "interaction"]
    codes = list(res.segments.index)
    data = {"segments": [names[c] for c in codes],
            **{e: {names[c]: round(b.value(f"attr.{p}.{c}.{e}"), 10) for c in codes} for e in effects}}
    rows = [[Cell(names[c], align="left")] + [_cell(analysis, f"attr.{p}.{c}.{e}", signed=True, tone=True)
                                               for e in (*effects, "total")] for c in codes]
    rows.append([Cell("Total", align="left", bold=True)] +
                [_cell(analysis, f"attr.{p}.TOTAL.{e}", signed=True, tone=True, bold=True) for e in (*effects, "total")])
    excess = fmt(b.value(f"perf.TOTAL.{p}.ret") - b.value(f"perf.TOTAL.{p}.bench"), "pct", b.currency)
    method = "Carino" if res.method == "carino" else "GRAP"
    total = b.value(f"attr.{p}.TOTAL.total")
    lead = (f"Over {PERIOD_LABELS[p].lower()}, the fund {'outperformed' if total >= 0 else 'underperformed'} its "
            f"benchmark by {fmt(abs(total), 'pct', b.currency)}. Allocation measures the effect of holding more or less "
            f"than the strategic weight in each asset class; selection measures each manager against its own benchmark.")
    return Section(s.title or "Attribution", [
        Paragraph(lead, "lead"),
        Chart("attribution", f"Attribution by mandate ({PERIOD_LABELS[p].lower()})", data),
        Table(["Mandate", "Allocation", "Selection", "Interaction", "Total"], rows,
              note=f"Brinson-Fachler attribution, monthly effects {method}-linked so they sum exactly to the "
                   f"compounded excess return ({excess}).")
    ])


def _risk(analysis: Analysis, s: SectionSpec, **_) -> Section | None:
    risk_p = "3y" if "3y" in analysis.periods else ("1y" if "1y" in analysis.periods else None)
    if risk_p is None:
        return None
    names = _names(analysis)
    rows = []
    for code in [*analysis.fund_codes(), "TOTAL"]:
        t = code == "TOTAL"
        rows.append([Cell("Total fund" if t else names[code], align="left", bold=t)] +
                    [_cell(analysis, f"risk.{code}.{risk_p}.{m}", bold=t) for m in ("vol", "te", "ir", "sharpe", "maxdd")])
    return Section(s.title or "Risk", [Table(
        ["Mandate", "Volatility", "Tracking error", "Information ratio", "Sharpe ratio", "Max drawdown"], rows,
        note="Volatility and tracking error are annualised standard deviations of monthly returns / excess returns.")])


def _funding(analysis: Analysis, s: SectionSpec, **_) -> Section | None:
    if analysis.funding is None:
        return Section(s.title or "Funding", [Paragraph("No liability data loaded; funding analysis unavailable.", "note")])
    b = analysis.facts
    blocks = [KPIGrid([
        KPI("Funding ratio", fmt(b.value("funding.ratio"), "pct"), "funding.ratio"),
        KPI("Liabilities", fmt(b.value("funding.liabilities"), "money", b.currency), "funding.liabilities"),
        KPI("Surplus / (deficit)", fmt(b.value("funding.surplus"), "money", b.currency), "funding.surplus",
            tone="good" if b.value("funding.surplus") >= 0 else "bad"),
        KPI("Hedge ratio", fmt(b.value("funding.hedge_ratio"), "pct"), "funding.hedge_ratio"),
        KPI("Liability duration", fmt(b.value("funding.liab_duration"), "years"), "funding.liab_duration"),
    ])]
    stress = analysis.funding["stress"]
    blocks.append(Chart("stress", "Stress tests: change in funding ratio",
                        {"scenarios": [x["scenario"] for x in stress],
                         "changes": [round(x["change_in_funding_ratio"], 10) for x in stress]}))
    blocks.append(Table(["Scenario", "Funding ratio after", "Change"],
                        [[Cell(x["scenario"], align="left"), _cell(analysis, f"funding.stress.{i}.ratio"),
                          _cell(analysis, f"funding.stress.{i}.change", signed=True, tone=True)]
                         for i, x in enumerate(stress)],
                        note="Liabilities are revalued on a shifted zero curve bootstrapped from government par yields; "
                             "rate-sensitive assets move by -duration x shift; growth assets take the equity shock."))
    sim = analysis.funding.get("simulation")
    if s.include_simulation and sim:
        blocks.append(Paragraph(
            f"The median projected funding ratio in ten years is {fmt(sim['median_end'], 'pct')}, with a "
            f"{fmt(sim['prob_fully_funded_end'], 'pct', decimals=0)} probability of being fully funded, assuming the "
            f"deficit is paid off by the sponsor over ten years. This illustrates the range of outcomes and is not an "
            f"actuarial valuation.", "lead"))
        blocks.append(Chart("funding_fan", "Projected funding ratio (10 years)", sim,
                            caption=f"{sim['n_paths']:,} simulated paths of interest rates and growth-asset returns."))
    return Section(s.title or "Funding", blocks)


def _data_quality(analysis: Analysis, s: SectionSpec, breaks: list[dict] | None = None, **_) -> Section:
    b = analysis.facts
    breaks = breaks or []
    names = _names(analysis)
    n_open_mat = int(b.value("recon.open_material"))
    lead = (f"Every monthly return was checked against the fund manager's own figures. "
            f"{len(breaks)} difference(s) above tolerance were found in the reporting history; "
            f"{n_open_mat} material item(s) remain open.")
    rows = []
    for br in breaks:
        res = br["status"] if br["status"] == "open" else f"{br['resolution']} accepted"
        rows.append([Cell(names.get(br["fund_code"], br["fund_code"]), align="left"),
                     Cell(br["month"][:7], align="left"),
                     Cell(br["break_type"].replace("_", " "), align="left"),
                     Cell("–" if br["custodian_value"] is None else f"{br['custodian_value'] * 100:.2f}%"),
                     Cell("–" if br["manager_value"] is None else f"{br['manager_value'] * 100:.2f}%"),
                     Cell(res, align="left", tone="bad" if br["status"] == "open" and br["severity"] == "material" else "neutral"),
                     Cell(br.get("reason") or "", align="left")])
    blocks = [Paragraph(lead, "lead")]
    if rows:
        blocks.append(Table(["Mandate", "Month", "Issue", "Custodian", "Manager", "Outcome", "Reason"], rows))
    return Section(s.title or "Data quality", blocks)


def _lineage(analysis: Analysis, s: SectionSpec, **_) -> Section:
    b = analysis.facts
    ids = ["mv.TOTAL.end", "perf.TOTAL.3m.ret", "perf.TOTAL.3m.excess", "perf.TOTAL.1y.ret",
           "attr.1y.TOTAL.total", "funding.liabilities", "funding.ratio", "funding.hedge_ratio"]
    rows = []
    for fid in ids:
        if fid not in b:
            continue
        f = b[fid]
        depth_note = f"{len(f.inputs)} input figures" if f.inputs else "; ".join(f.sources[:2])
        rows.append([Cell(f.label, align="left"), Cell(fmt(f.value, f.unit, b.currency), fid),
                     Cell(f.formula, align="left"), Cell(depth_note, align="left")])
    return Section(s.title or "Lineage", [
        Paragraph("Every figure in this report is traceable: it is computed by a documented formula from other figures, "
                  "down to individual cells in the custodian, manager, benchmark and actuarial files. The interactive "
                  "(HTML) version lets you click any number to see its full derivation.", "lead"),
        Table(["Figure", "Value", "How it is calculated", "Built from"], rows),
    ])


_HANDLERS = {
    "kpis": _kpis,
    "commentary": _commentary,
    "performance_table": _performance,
    "chart": _chart,
    "allocation": _allocation,
    "attribution": _attribution,
    "risk": _risk,
    "funding": _funding,
    "data_quality": _data_quality,
    "lineage_appendix": _lineage,
}
