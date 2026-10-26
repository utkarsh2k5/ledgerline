"""LLM providers behind one tiny interface, so the model is swappable.

* GeminiProvider   - Google Gemini REST API (free tier works; one call per report)
* TemplateProvider - deterministic writer used offline and as the safe fallback
* HallucinatingProvider - demo/test double: its first draft contains a wrong
  number and a wrong direction word, so you can watch the verifier catch it.
"""
from __future__ import annotations

import time
from typing import Protocol

import httpx

from ..config import settings


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, context: dict) -> str: ...


class GeminiProvider:
    """Gemini over REST, with retries when Google is overloaded.

    503/5xx ("model is experiencing high demand") is common on the free tier and
    usually clears in seconds, so each model gets a couple of retries with backoff.
    If it stays busy, or its free quota is used up (429), we move on to the next
    model in the list (a lighter Flash-Lite model by default).
    """

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    BUSY = {500, 502, 503, 504}

    def __init__(self, api_key: str, model: str, fallback_models: tuple[str, ...] = (),
                 timeout: float = 45.0, retries: int = 2, backoff: float = 1.5) -> None:
        self.api_key, self.timeout, self.retries, self.backoff = api_key, timeout, retries, backoff
        self.models = [model] + [m for m in fallback_models if m and m != model]
        self.name = f"gemini:{model}"

    def generate(self, prompt: str, context: dict) -> str:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        }
        problems: list[str] = []
        for model in self.models:
            for attempt in range(self.retries + 1):
                try:
                    resp = httpx.post(self.URL.format(model=model), json=body, timeout=self.timeout,
                                      headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
                except httpx.HTTPError as exc:  # network blip: treat like "busy"
                    problems.append(f"{model}: request failed ({exc.__class__.__name__})")
                    if attempt < self.retries:
                        time.sleep(self.backoff * 2 ** attempt)
                        continue
                    break
                if resp.status_code in self.BUSY:
                    problems.append(f"{model}: HTTP {resp.status_code} {_message(resp)}")
                    if attempt < self.retries:
                        time.sleep(self.backoff * 2 ** attempt)
                        continue
                    break  # still busy: try the next model
                if resp.status_code in (404, 429):
                    # unknown model name, or this model's free quota is used up: next model
                    problems.append(f"{model}: HTTP {resp.status_code} {_message(resp)}")
                    break
                if resp.status_code >= 400:  # bad key etc.: no point trying other models
                    raise ProviderError(f"Gemini returned HTTP {resp.status_code}: {_message(resp)}")
                try:
                    parts = resp.json()["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts).strip()
                except (KeyError, IndexError, ValueError) as exc:
                    raise ProviderError(f"Unexpected Gemini response: {resp.text[:300]}") from exc
                if not text:
                    raise ProviderError("Gemini returned an empty response")
                self.name = f"gemini:{model}"
                return text
        raise ProviderError("Gemini unavailable after retries: " + "; ".join(problems[-3:]))


def _message(resp: httpx.Response) -> str:
    """Pull the human-readable message out of a Google API error, if there is one."""
    try:
        return str(resp.json()["error"]["message"])[:200]
    except (ValueError, KeyError, TypeError):
        return resp.text[:200]


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
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_models)
    if kind == "mock-hallucinate":
        return HallucinatingProvider()
    return TemplateProvider()
