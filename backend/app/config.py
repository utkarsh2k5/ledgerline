"""Application settings.

Read from environment variables, with an optional `.env` file in the backend
folder. Kept dependency-free on purpose (no python-dotenv / pydantic-settings).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'ledgerline.db'}"
        )
    )
    jwt_secret: str = field(
        default_factory=lambda: os.environ.get("JWT_SECRET", "dev-only-secret-change-me-in-production-please")
    )
    jwt_ttl_minutes: int = field(
        default_factory=lambda: int(os.environ.get("JWT_TTL_MINUTES", "480"))
    )
    # "gemini" | "mock" | "mock-hallucinate" (demo: injects a wrong number)
    ai_provider: str = field(
        default_factory=lambda: os.environ.get("AI_PROVIDER", "mock").lower()
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY") or None
    )
    # An alias that tracks Google's current Flash model. Override if you want
    # to pin a specific version (see README).
    gemini_model: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    )
    # Tried in order when the main model is overloaded or out of free quota.
    gemini_fallback_models: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest").split(",") if m.strip()
        )
    )
    storage_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("STORAGE_DIR", str(BACKEND_DIR / "storage"))
        )
    )
    # Run the job worker inside the API process (handy for local dev / SQLite).
    embedded_worker: bool = field(
        default_factory=lambda: _bool("EMBEDDED_WORKER", True)
    )
    recon_tolerance_bps: float = field(
        default_factory=lambda: float(os.environ.get("RECON_TOLERANCE_BPS", "5"))
    )
    material_break_bps: float = field(
        default_factory=lambda: float(os.environ.get("MATERIAL_BREAK_BPS", "25"))
    )
    # One-click role access (no passwords) for the public demo. Turn off for real use.
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))
    risk_free_annual: float = field(
        default_factory=lambda: float(os.environ.get("RISK_FREE_ANNUAL", "0.04"))
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.environ.get(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if o.strip()
        )
    )


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
