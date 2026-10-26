"""Numeric fact-checker for AI-written commentary.

LLMs are good at prose and bad at numbers. Before a generated paragraph can
go into a client report, every number in it must match a computed fact, and
every "outperformed / lagged" claim must agree with the sign of the excess
return it talks about. Anything that fails is rejected.

Checks
------
1. Every numeric token (%, bps, percentage points, £m/£bn, years, plain
   decimals) must equal some allowed fact *at the precision written*
   (e.g. "4.7%" matches 0.04746 but not 0.0481).
2. Explicit signs must agree ("-1.2%" can't match +1.2%).
3. Direction words near a matched excess/attribution number must agree with
   that number's sign.
4. "Surplus" can't be claimed when the scheme is in deficit (and vice versa).

Known limits (documented, tested): it cannot judge causal claims ("because
equities rallied") and only knows the directions it has words for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..analytics.facts import Fact

_NUM = re.compile(
    r"(?P<sign>[-+−])?\s?(?P<cur>[£$€₹])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suffix>%|percentage points?|pts|bps|basis points|bn|billion|m\b|million|yrs|years?)?",
    re.IGNORECASE,
)
# Sentence split is naive (breaks on "e.g."), good enough for templated finance prose.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

POSITIVE = ["outperform", "ahead of", "beat", "beating", "exceeded", "above the benchmark", "added",
            "contributed positively", "ahead"]
NEGATIVE = ["underperform", "behind", "lagged", "lagging", "trailed", "below the benchmark", "detracted",
            "cost", "fell short"]
ALLOWED_PLAIN = {100.0}  # "100% funded" is a threshold, not a claim


@dataclass
class Issue:
    kind: str
    message: str
    token: str | None = None
    sentence: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "token": self.token, "sentence": self.sentence}


@dataclass
class Verification:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)

    def feedback(self) -> str:
        return "\n".join(f"- {i.message}" for i in self.issues)


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def _candidates(token_value: float, suffix: str | None, decimals: int):
    """Yield (unit, value_in_fact_units, tolerance) interpretations of a token."""
    s = (suffix or "").lower()
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    if s in {"%", "percentage point", "percentage points", "pts"}:
        yield "pct", token_value / 100, tol / 100
    elif s in {"bps", "basis points"}:
        yield "pct", token_value / 10_000, tol / 10_000
        yield "bps", token_value, tol
    elif s in {"bn", "billion"}:
        yield "money", token_value * 1e9, tol * 1e9
    elif s in {"m", "million"}:
        yield "money", token_value * 1e6, tol * 1e6
    elif s in {"yrs", "year", "years"}:
        yield "years", token_value, tol
    else:
        yield "ratio", token_value, tol
        yield "money", token_value, tol
        yield "count", token_value, tol


def _is_ignorable(m: re.Match, text: str) -> bool:
    num, suffix = m.group("num"), (m.group("suffix") or "").lower()
    value = float(num.replace(",", ""))
    before = text[max(0, m.start() - 2): m.start()]
    after = text[m.end(): m.end() + 8].lower()
    if not suffix and "." not in num and 1990 <= value <= 2100:
        return True                                   # a year
    if before.endswith("Q") or before.endswith("H"):
        return True                                   # Q3, H1
    if suffix in {"year", "years"} and value <= 50 and "." not in num and not after.startswith(("s.", ")")):
        # "3 years" as a period, unless a duration value with decimals
        return True
    if not suffix and value.is_integer() and value <= 36 and after.lstrip("-").startswith(("month", "year", "-year", "-month")):
        return True
    if suffix == "%" and value in ALLOWED_PLAIN:
        return True
    if re.match(r"(st|nd|rd|th)\b", text[m.end(): m.end() + 2]):
        return True                                   # 5th percentile
    return False


def verify(text: str, facts: list[Fact]) -> Verification:
    issues: list[Issue] = []
    matches: list[dict] = []
    sentences = [s for s in _SENTENCE.split(text.strip()) if s]

    for sentence in sentences:
        sent_matches = []
        for m in _NUM.finditer(sentence):
            if _is_ignorable(m, sentence):
                continue
            raw = m.group(0).strip()
            sign = m.group("sign")
            value = float(m.group("num").replace(",", ""))
            decimals = _decimals(m.group("num"))
            found = None
            for unit, v, tol in _candidates(value, m.group("suffix"), decimals):
                for f in facts:
                    if f.unit != unit:
                        continue
                    fv = f.value
                    if sign in {"-", "−"}:
                        if abs(-v - fv) <= tol:
                            found = f
                    elif sign == "+":
                        if abs(v - fv) <= tol:
                            found = f
                    elif abs(v - abs(fv)) <= tol:
                        found = f
                    if found:
                        break
                if found:
                    break
            if found is None:
                issues.append(Issue("unsupported_number",
                                    f"'{raw}' does not match any computed figure at the precision written",
                                    raw, sentence))
            else:
                sent_matches.append((m.start(), found, raw))
                matches.append({"token": raw, "fact_id": found.id})

        lower = sentence.lower()
        for pos, fact, raw in sent_matches:
            if not (".excess" in fact.id or fact.id.startswith("attr.") or fact.id.endswith(".change")):
                continue
            direction = _nearest_direction(lower, pos)
            if direction is None or abs(fact.value) < 5e-5:
                continue
            if (direction > 0) != (fact.value > 0):
                issues.append(Issue("wrong_direction",
                                    f"'{raw}' is described as {'positive' if direction > 0 else 'negative'} "
                                    f"but {fact.label} is {'positive' if fact.value > 0 else 'negative'}",
                                    raw, sentence))
    return Verification(ok=not issues, issues=issues, matches=matches)


def check_claims(text: str, facts_by_id: dict[str, Fact]) -> list[Issue]:
    """Non-numeric claims that can still be checked against facts."""
    issues = []
    surplus = facts_by_id.get("funding.surplus")
    for sentence in _SENTENCE.split(text):
        lower = sentence.lower()
        if surplus is not None:
            if surplus.value < 0 and re.search(r"\bsurplus\b", lower) and "deficit" not in lower:
                issues.append(Issue("wrong_claim", "Claims a surplus but the scheme is in deficit", None, sentence))
            if surplus.value > 0 and re.search(r"\bdeficit\b", lower) and "surplus" not in lower:
                issues.append(Issue("wrong_claim", "Claims a deficit but the scheme is in surplus", None, sentence))
            if surplus.value < 0 and re.search(r"(?<!not )\bfully funded\b", lower) and not re.search(
                    r"\b(not|below|short of|towards|probability|chance)\b", lower):
                issues.append(Issue("wrong_claim", "Claims the scheme is fully funded but it is in deficit", None, sentence))
    return issues


def _nearest_direction(lower: str, pos: int) -> int | None:
    best: tuple[int, int] | None = None
    for words, sign in ((POSITIVE, 1), (NEGATIVE, -1)):
        for w in words:
            for mm in re.finditer(re.escape(w), lower):
                d = abs(mm.start() - pos)
                if best is None or d < best[0]:
                    best = (d, sign)
    if best is None or best[0] > 90:
        return None
    return best[1]
