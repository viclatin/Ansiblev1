"""GET /health — service liveness and data freshness check."""
from __future__ import annotations

from fastapi import APIRouter

from api.config import settings
from api.data import load_manifest
from api.models import HealthResponse, ManifestResponse, TableInfo

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Service health and data freshness")
def get_health() -> HealthResponse:
    manifest_raw = load_manifest(settings.powerbi_data_dir)

    manifest = None
    if manifest_raw:
        tables = [
            TableInfo(**t)
            for t in manifest_raw.get("tables", [])
        ]
        manifest = ManifestResponse(
            schema_version=manifest_raw.get("schema_version", ""),
            generated_at=manifest_raw.get("generated_at", ""),
            tables=tables,
        )

    return HealthResponse(
        status="ok",
        data_dir=str(settings.powerbi_data_dir),
        manifest=manifest,
    )
