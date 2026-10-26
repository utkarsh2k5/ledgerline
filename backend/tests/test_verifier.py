from datetime import date

import pytest
from sqlalchemy import select

from app.ai import commentary as C
from app.ai.providers import ProviderError
from app.ai.verifier import check_claims, verify
from app.analytics.engine import build_analysis
from app.analytics.facts import Fact
from app.models import Scheme

FACTS = [
    Fact("perf.TOTAL.3m.ret", "Total return 3m", 0.04064, "pct", ""),
    Fact("perf.TOTAL.3m.bench", "Benchmark 3m", 0.04318, "pct", ""),
    Fact("perf.TOTAL.3m.excess", "Excess 3m", -0.00254, "pct", ""),
    Fact("mv.TOTAL.end", "Assets", 1_541_700_000.0, "money", ""),
    Fact("funding.surplus", "Surplus", -108_600_000.0, "money", ""),
    Fact("funding.liab_duration", "Duration", 15.61, "years", ""),
]


def test_accepts_numbers_at_written_precision():
    text = "The fund returned 4.06% (about 4.1%), behind the benchmark of 4.32% by 0.25%. Assets were £1.54bn."
    assert verify(text, FACTS).ok


def test_rejects_invented_number():
    v = verify("The fund returned 4.6% this quarter.", FACTS)
    assert not v.ok and v.issues[0].kind == "unsupported_number"


def test_rejects_wrong_direction():
    v = verify("The fund outperformed its benchmark by 0.25% this quarter.", FACTS)
    assert [i.kind for i in v.issues] == ["wrong_direction"]


def test_rejects_wrong_explicit_sign():
    assert not verify("Relative performance was +0.25%.", FACTS).ok
    assert verify("Relative performance was -0.25%.", FACTS).ok


def test_ignores_years_periods_and_thresholds():
    text = "In Q3 2026, over three years and the last 12 months, the scheme aims to be 100% funded. Duration is 15.6 years."
    assert verify(text, FACTS).ok


def test_money_and_bps_units():
    assert verify("The deficit is £108.6m.", FACTS).ok
    assert verify("It lagged by 25 bps.", FACTS).ok
    assert not verify("The deficit is £118.6m.", FACTS).ok


def test_claims_checker_catches_surplus_when_in_deficit():
    issues = check_claims("The scheme is now in surplus.", {f.id: f for f in FACTS})
    assert issues and issues[0].kind == "wrong_claim"


@pytest.fixture()
def analysis(db):
    return build_analysis(db, db.scalar(select(Scheme)), date(2026, 9, 30))


def test_template_commentary_always_passes_its_own_checker(analysis):
    text = C.template_commentary(analysis)
    assert C._check(text, C.fact_sheet(analysis)) == []


def test_hallucinating_model_is_caught_then_fixed_on_retry(analysis, monkeypatch):
    from app.ai.providers import HallucinatingProvider

    provider = HallucinatingProvider()
    monkeypatch.setattr(C, "get_provider", lambda: provider)
    out = C.generate_commentary(analysis)
    assert out.status == "verified"
    kinds = {i["kind"] for i in out.issues}
    assert {"unsupported_number", "wrong_direction"} <= kinds
    assert all(i.get("attempt") == 1 for i in out.issues)


def test_provider_failure_falls_back_to_template(analysis, monkeypatch):
    class Broken:
        name = "broken"

        def generate(self, prompt, context):
            raise ProviderError("quota exceeded")

    monkeypatch.setattr(C, "get_provider", lambda: Broken())
    out = C.generate_commentary(analysis)
    assert out.status == "fallback"
    assert out.provider == "template"
    assert out.issues[0]["kind"] == "provider_error"


def test_model_that_never_gets_it_right_falls_back(analysis, monkeypatch):
    class Liar:
        name = "liar"

        def generate(self, prompt, context):
            return "Assets returned 9.99% and the scheme is fully funded."

    monkeypatch.setattr(C, "get_provider", lambda: Liar())
    out = C.generate_commentary(analysis)
    assert out.status == "fallback"
    assert {i["attempt"] for i in out.issues} == {1, 2}
    assert "9.99%" not in out.text


def test_prompt_contains_only_fact_sheet_numbers(analysis):
    prompt = C.build_prompt(analysis, C.fact_sheet(analysis), 150)
    assert "STRICT RULES" in prompt
    assert "4.06%" in prompt


def test_gemini_provider_request_and_errors(monkeypatch):
    import httpx

    from app.ai.providers import GeminiProvider

    seen = {}

    def fake_post(url, json, timeout, headers):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Draft text."}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    g = GeminiProvider("k-123", "gemini-flash-latest")
    assert g.generate("prompt", {}) == "Draft text."
    assert seen["url"].endswith("/models/gemini-flash-latest:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "k-123"
    assert seen["json"]["contents"][0]["parts"][0]["text"] == "prompt"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="quota"))
    with pytest.raises(ProviderError, match="quota"):
        g.generate("prompt", {})
