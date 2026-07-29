"""Network ops Power BI data API — read-only FastAPI service.

Start with:
    cd /home/victor/ansible
    API_KEY=your-secret ./scripts/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

Power BI Web connector URL: http://<host>:8000/v1/snapshots/compliance/latest
"""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader

from api.config import settings
from api.routers import compliance_data, health_data, system

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Network Ops Power BI API",
    description=(
        "Read-only REST API that exposes device health and compliance data "
        "for Power BI dashboards. All data is served from the pre-generated "
        "CSV exports produced by scripts/export_powerbi.py."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS — required for Power BI Service browser-based refresh
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["X-API-Key", "Authorization"],
)

# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Annotated[str | None, Security(_api_key_header)] = None) -> None:
    """Enforce X-API-Key when API_KEY env var is set; skip auth in dev mode."""
    if not settings.api_key:
        # No key configured — allow all requests (local dev).
        return
    if api_key is None or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(system.router)
app.include_router(
    health_data.router,
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    compliance_data.router,
    dependencies=[Depends(verify_api_key)],
)
