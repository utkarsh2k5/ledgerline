"""FastAPI entry point.

Local dev:   uvicorn app.main:app --reload   (frontend runs separately on :5173)
Production:  the built frontend is copied into backend/static and served from here,
             so the whole thing deploys as one web service.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes_core import router as core_router
from .api.routes_data import router as data_router
from .config import BACKEND_DIR, settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
STATIC_DIR = Path(os.environ.get("STATIC_DIR", BACKEND_DIR / "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = None
    if settings.embedded_worker:
        from .jobs.worker import start_embedded

        stop = start_embedded()
    yield
    if stop is not None:
        stop.set()


app = FastAPI(
    title="Ledgerline API",
    version=__version__,
    description="Performance reporting for DB pension schemes: reconciliation, attribution, "
                "report generation and number-level lineage.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(core_router, prefix="/api")
app.include_router(data_router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "version": __version__, "ai_provider": settings.ai_provider}


if (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # React Router handles client-side routes, so anything that isn't a real
        # file (and isn't the API) gets index.html.
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
