"""LLM providers behind one tiny interface, so the model is swappable.

* GeminiProvider   - Google Gemini REST API (free tier works; one call per report)
* TemplateProvider - deterministic writer used offline and as the safe fallback
* HallucinatingProvider - demo/test double: its first draft contains a wrong
  number and a wrong direction word, so you can watch the verifier catch it.
"""
from __future__ import annotations

from typing import Protocol

import httpx

from ..config import settings


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, context: dict) -> str: ...


class GeminiProvider:
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float = 45.0) -> None:
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.name = f"gemini:{model}"

    def generate(self, prompt: str, context: dict) -> str:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        }
        try:
            resp = httpx.post(self.URL.format(model=self.model), json=body, timeout=self.timeout,
                              headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc
        if resp.status_code == 429:
            raise ProviderError("Gemini rate limit / free-tier quota reached (HTTP 429)")
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"Unexpected Gemini response: {resp.text[:300]}") from exc
        if not text:
            raise ProviderError("Gemini returned an empty response")
        return text


class TemplateProvider:
    """Deterministic, rule-based commentary written only from facts."""

    name = "template"

    def generate(self, prompt: str, context: dict) -> str:
        from .commentary import template_commentary

        return template_commentary(context["analysis"])


class HallucinatingProvider:
    """Like an LLM having a bad day: first draft inflates a number and flips a direction."""

    name = "mock-hallucinate"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, context: dict) -> str:
        from .commentary import template_commentary

        self.calls += 1
        text = template_commentary(context["analysis"])
        if self.calls == 1:
            book = context["analysis"].facts
            real = book.value("perf.TOTAL.3m.ret")
            text = text.replace(f"{real * 100:.2f}%", f"{(real + 0.0061) * 100:.2f}%", 1)
            text = text.replace("ahead of", "behind", 1) if "ahead of" in text else text.replace("behind", "ahead of", 1)
        return text


def get_provider() -> Provider:
    kind = settings.ai_provider
    if kind == "gemini":
        if not settings.gemini_api_key:
            raise ProviderError("AI_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if kind == "mock-hallucinate":
        return HallucinatingProvider()
    return TemplateProvider()
