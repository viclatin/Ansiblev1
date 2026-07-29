"""Health data endpoints: device snapshots and per-check detail."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Query

from api.config import settings
from api.data import filter_rows, latest_per_hostname, load_csv
from api.models import ListResponse

router = APIRouter(prefix="/v1", tags=["health"])


@router.get(
    "/snapshots/health/latest",
    response_model=ListResponse,
    summary="Latest health snapshot per device",
)
def get_health_snapshots_latest(
    hostname: Annotated[Optional[str], Query(description="Filter to a specific hostname")] = None,
) -> ListResponse:
    rows = load_csv(settings.powerbi_data_dir, "device_health_snapshots.csv")
    rows = latest_per_hostname(rows)
    if hostname:
        hostname_lower = hostname.lower()
        rows = [r for r in rows if r.get("hostname", "").lower() == hostname_lower]
    # Strip the source_file path — internal detail, not needed by Power BI.
    for row in rows:
        row.pop("source_file", None)
        row.pop("report_type", None)
        # Trim ios_version to first line — full text is too noisy for Power BI.
        if row.get("ios_version"):
            row["ios_version"] = row["ios_version"].splitlines()[0].strip()
    return ListResponse(count=len(rows), data=rows)


@router.get(
    "/health/checks",
    response_model=ListResponse,
    summary="Health check and probe results",
)
def get_health_checks(
    hostname: Annotated[Optional[str], Query(description="Filter to a specific hostname")] = None,
    check_name: Annotated[Optional[str], Query(description="Filter to a specific check name")] = None,
    status: Annotated[Optional[str], Query(description="Filter by status (ok, warning, not_supported, …)")] = None,
    since: Annotated[Optional[str], Query(description="ISO 8601 timestamp — only rows at or after this time")] = None,
    actionable_only: Annotated[
        bool,
        Query(
            description=(
                "When true (default), excludes non-actionable statuses "
                "(not_supported, not_applicable, blank) unless status is explicitly requested."
            )
        ),
    ] = True,
) -> ListResponse:
    rows = load_csv(settings.powerbi_data_dir, "health_checks.csv")
    rows = filter_rows(rows, hostname=hostname, status=status, since=since)
    if actionable_only and status is None:
        excluded_statuses = {"not_supported", "not_applicable", ""}
        rows = [r for r in rows if r.get("status", "").strip().lower() not in excluded_statuses]
    if check_name:
        check_name_lower = check_name.lower()
        rows = [r for r in rows if r.get("check_name", "").lower() == check_name_lower]
    for row in rows:
        row.pop("source_file", None)
        row.pop("report_type", None)
    return ListResponse(count=len(rows), data=rows)
