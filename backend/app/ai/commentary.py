"""AI-drafted investment commentary, gated by the numeric fact-checker.

Flow:  fact sheet -> LLM draft -> verify -> (retry once with the errors) ->
       verified text, or a deterministic template if the AI can't get it right.
The report shows which path was taken; nothing unverified reaches a client.
"""
from __future__ import annotations

import logging

from ..analytics.engine import Analysis
from ..analytics.facts import Fact, fmt
from ..reporting.ir import Commentary
from .providers import ProviderError, TemplateProvider, get_provider
from .verifier import check_claims, verify

log = logging.getLogger(__name__)


def fact_sheet(analysis: Analysis) -> list[Fact]:
    """The only facts the model is allowed to use."""
    b = analysis.facts
    ids = []
    for p in ("3m", "1y", "3y"):
        ids += [f"perf.TOTAL.{p}.ret", f"perf.TOTAL.{p}.bench", f"perf.TOTAL.{p}.excess"]
    for code in analysis.fund_codes():
        ids += [f"perf.{code}.3m.excess", f"perf.{code}.1y.excess"]
    if "1y" in analysis.attribution:
        ids += [f"attr.1y.TOTAL.{e}" for e in ("allocation", "selection", "interaction")]
        ids += [f"attr.1y.{c}.total" for c in analysis.fund_codes()]
    ids += ["mv.TOTAL.end", "funding.ratio", "funding.surplus", "funding.hedge_ratio", "funding.liab_duration",
            "funding.stress.0.change", "funding.stress.2.change"]
    return [b[i] for i in ids if i in b]


def build_prompt(analysis: Analysis, facts: list[Fact], words: int, feedback: str | None = None) -> str:
    cur = analysis.facts.currency
    lines = "\n".join(f"- {f.label}: {fmt(f.value, f.unit, cur)}" for f in facts)
    names = "\n".join(f"- {r.fund_code} = {r.fund_name} ({r.manager})" for r in analysis.funds.itertuples())
    prompt = f"""You are an investment consultant writing the quarterly commentary for the trustees of
{analysis.scheme.name}, a UK defined benefit pension scheme. Period end: {analysis.period_end:%d %B %Y}.

Write about {words} words of plain, professional prose (no headings, no bullet points, no markdown).
Cover: total fund performance vs benchmark (quarter and one year), the mandates that helped or hurt most,
what attribution says about allocation vs manager selection, and the funding position and hedging.

STRICT RULES:
1. Use ONLY the figures listed below, written EXACTLY as shown (same rounding and units).
2. Do not calculate new numbers (no sums, differences, averages or conversions).
3. Write periods in words ("the quarter", "one year", "three years"), never as digits.
4. "Outperformed/ahead/added" only for positive excess figures; "underperformed/behind/detracted" only for negative.
5. Refer to mandates by name, not code. No forecasts or recommendations.

Mandates:
{names}

Figures:
{lines}
"""
    if feedback:
        prompt += f"\nYour previous draft was REJECTED by the fact-checker for these reasons:\n{feedback}\nRewrite it, fixing every issue.\n"
    return prompt


def _check(text: str, facts: list[Fact]) -> list[dict]:
    result = verify(text, facts)
    issues = result.issues + check_claims(text, {f.id: f for f in facts})
    return [i.to_dict() for i in issues]


def generate_commentary(analysis: Analysis, words: int = 160) -> Commentary:
    facts = fact_sheet(analysis)
    used_ids = [f.id for f in facts]
    attempts_log: list[dict] = []
    try:
        provider = get_provider()
    except ProviderError as exc:
        attempts_log.append({"kind": "provider_error", "message": str(exc)})
        provider = None

    if provider is not None:
        feedback = None
        for attempt in (1, 2):
            try:
                draft = provider.generate(build_prompt(analysis, facts, words, feedback), {"analysis": analysis})
            except ProviderError as exc:
                attempts_log.append({"kind": "provider_error", "message": str(exc), "attempt": attempt})
                break
            issues = _check(draft, facts)
            if not issues:
                for i in attempts_log:
                    i.setdefault("resolved_on_retry", True)
                return Commentary(text=draft.strip(), status="verified", provider=provider.name,
                                  issues=attempts_log, fact_ids=used_ids)
            for i in issues:
                i["attempt"] = attempt
            attempts_log.extend(issues)
            feedback = "\n".join(f"- {i['message']}" + (f" (in: \"{i['sentence']}\")" if i.get("sentence") else "")
                                 for i in issues)
            log.warning("Commentary attempt %s rejected: %s", attempt, feedback)

    text = template_commentary(analysis)
    final_issues = _check(text, facts)
    if final_issues:  # should never happen; tests guard this
        raise RuntimeError(f"Template commentary failed verification: {final_issues}")
    # Reaching here means the AI provider failed or kept failing verification.
    return Commentary(text=text, status="fallback", provider=TemplateProvider.name,
                      issues=attempts_log, fact_ids=used_ids)


def template_commentary(analysis: Analysis) -> str:
    b, cur = analysis.facts, analysis.facts.currency

    def d(fid: str) -> str:
        f = b[fid]
        return fmt(abs(f.value) if f.unit != "money" else f.value, f.unit, cur)

    def da(fid: str) -> str:
        f = b[fid]
        return fmt(abs(f.value), f.unit, cur)

    def pts(fid: str) -> str:
        return f"{abs(b.value(fid)) * 100:.2f} percentage points"

    name = dict(zip(analysis.funds["fund_code"], analysis.funds["fund_name"]))
    parts = []
    ex3 = b.value("perf.TOTAL.3m.excess")
    parts.append(
        f"Over the quarter the Scheme's assets returned {d('perf.TOTAL.3m.ret')}"
        if b.value("perf.TOTAL.3m.ret") >= 0 else f"Over the quarter the Scheme's assets fell by {d('perf.TOTAL.3m.ret')}"
    )
    parts[-1] += (f", {'ahead of' if ex3 >= 0 else 'behind'} the benchmark return of {d('perf.TOTAL.3m.bench')} "
                  f"by {da('perf.TOTAL.3m.excess')}.")
    if "perf.TOTAL.1y.ret" in b:
        ex1 = b.value("perf.TOTAL.1y.excess")
        parts.append(
            f"Over one year the fund returned {d('perf.TOTAL.1y.ret')} against a benchmark of "
            f"{d('perf.TOTAL.1y.bench')}, {'outperforming' if ex1 >= 0 else 'underperforming'} by {da('perf.TOTAL.1y.excess')}."
        )
    q = sorted(analysis.fund_codes(), key=lambda c: b.value(f"perf.{c}.3m.excess"))
    best, worst = q[-1], q[0]
    if b.value(f"perf.{best}.3m.excess") > 0 and b.value(f"perf.{worst}.3m.excess") < 0:
        parts.append(
            f"Relative to benchmark, {name[best]} was the strongest mandate this quarter, ahead by "
            f"{da(f'perf.{best}.3m.excess')}, while {name[worst]} lagged by {da(f'perf.{worst}.3m.excess')}."
        )
    if "1y" in analysis.attribution:
        alloc, sel = b.value("attr.1y.TOTAL.allocation"), b.value("attr.1y.TOTAL.selection")
        parts.append(
            f"Attribution over one year shows asset allocation {'added' if alloc >= 0 else 'detracted'} "
            f"{da('attr.1y.TOTAL.allocation')} and manager selection {'added' if sel >= 0 else 'detracted'} "
            f"{da('attr.1y.TOTAL.selection')}."
        )
    if "funding.ratio" in b:
        surplus = b.value("funding.surplus")
        parts.append(
            f"The funding ratio stands at {d('funding.ratio')}, a {'surplus' if surplus >= 0 else 'deficit'} of "
            f"{da('funding.surplus')}, and the interest-rate hedge covers {d('funding.hedge_ratio')} of the "
            f"liabilities' sensitivity to rates."
        )
        if "funding.stress.0.change" in b:
            parts.append(
                f"In our stress tests, a fall of one percentage point in interest rates would reduce the funding "
                f"ratio by {pts('funding.stress.0.change')}, while a fall of a fifth in growth asset "
                f"values would reduce it by {pts('funding.stress.2.change')}."
            )
    return " ".join(parts)
