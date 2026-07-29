"""Compliance data endpoints: device snapshots and per-control detail."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Query

from api.config import settings
from api.data import filter_rows, latest_per_hostname, load_csv
from api.models import ListResponse

router = APIRouter(prefix="/v1", tags=["compliance"])


@router.get(
    "/snapshots/compliance/latest",
    response_model=ListResponse,
    summary="Latest compliance snapshot per device",
)
def get_compliance_snapshots_latest(
    hostname: Annotated[Optional[str], Query(description="Filter to a specific hostname")] = None,
) -> ListResponse:
    rows = load_csv(settings.powerbi_data_dir, "compliance_snapshots.csv")
    rows = latest_per_hostname(rows)
    if hostname:
        hostname_lower = hostname.lower()
        rows = [r for r in rows if r.get("hostname", "").lower() == hostname_lower]
    for row in rows:
        row.pop("source_file", None)
        row.pop("report_type", None)
    return ListResponse(count=len(rows), data=rows)


@router.get(
    "/compliance/controls",
    response_model=ListResponse,
    summary="Per-control compliance results",
)
def get_compliance_controls(
    hostname: Annotated[Optional[str], Query(description="Filter to a specific hostname")] = None,
    control_status: Annotated[Optional[str], Query(description="Filter by control status (PASS or FAIL)")] = None,
    since: Annotated[Optional[str], Query(description="ISO 8601 timestamp — only rows at or after this time")] = None,
) -> ListResponse:
    rows = load_csv(settings.powerbi_data_dir, "compliance_controls.csv")
    if hostname:
        hostname_lower = hostname.lower()
        rows = [r for r in rows if r.get("hostname", "").lower() == hostname_lower]
    if control_status:
        status_upper = control_status.upper().strip()
        rows = [r for r in rows if r.get("control_status", "").upper().strip() == status_upper]
    if since:
        rows = [r for r in rows if r.get("timestamp", "") >= since]
    for row in rows:
        row.pop("source_file", None)
        row.pop("report_type", None)
    return ListResponse(count=len(rows), data=rows)
