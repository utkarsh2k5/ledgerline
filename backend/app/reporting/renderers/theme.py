"""Shared visual identity for all output formats."""

NAVY = "17324D"
NAVY_2 = "2A4A6B"
INK = "1B1B1B"
INK_2 = "52514E"
INK_3 = "8A8984"
RULE = "D9D7D0"
BAND = "F3F2EE"
GOOD = "0B7A3E"
BAD = "C0392B"
WARN_BG = "FFF4D6"
WARN_INK = "7A5200"
ACCENT = "2A78D6"

TONE_HEX = {"good": GOOD, "bad": BAD, "warn": WARN_INK, "neutral": INK}

STATUS_TEXT = {
    "verified": "AI-drafted and verified: every figure was checked against the computed numbers before publication.",
    "fallback": "Standard commentary: the AI draft did not pass the numeric fact-check, so this rule-based text "
                "(generated directly from the computed figures) is shown instead.",
}


def status_line(status: str, provider: str) -> str:
    if status == "verified" and provider == "template":
        return "Commentary generated from the computed figures and verified."
    if status == "verified":
        return f"{STATUS_TEXT['verified']} (model: {provider})"
    return STATUS_TEXT.get(status, status)
