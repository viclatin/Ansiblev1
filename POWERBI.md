# Power BI Data Readiness

This repository now produces a curated analytics layer for Power BI under `reports/powerbi/`.

## Recommended tables

- `device_health_snapshots.csv`: one row per device report snapshot.
- `health_checks.csv`: one row per health check or probe result.
- `compliance_snapshots.csv`: one row per compliance report snapshot.
- `compliance_controls.csv`: one row per compliance control.
- `export_manifest.json`: refresh metadata and row counts for the current export.

## Model guidance

Use `hostname` plus `timestamp` as the main analysis keys. Keep the CSVs in a simple star-style model:

- Device snapshot table as the main fact table for trend charts.
- Health checks table for drill-down by check, status, and probe.
- Compliance snapshots table for score and status trends.
- Compliance controls table for failed-control analysis and remediation prioritization.

## Suggested Power BI visuals

- Compliance score trend by host.
- Compliance status distribution.
- Failed controls by device and by control name.
- Health status summary by host.
- CPU and memory trend lines.
- Interface state counts and probe reliability.

## Refresh workflow

1. Run `python3 scripts/export_powerbi.py` after new reports are created.
2. Point Power BI to the CSV files in `reports/powerbi/`.
3. Use `export_manifest.json` to confirm refresh time and row counts.
4. Keep the raw JSON reports as the source of truth; do not model Power BI directly against them.

## REST API

The API service in `api/` exposes all Power BI tables as JSON endpoints via FastAPI.

### Start the server

```bash
cd /home/victor/ansible

# No auth (local dev)
./scripts/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

# With API key
API_KEY=your-secret ./scripts/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service liveness, manifest, and row counts |
| GET | `/v1/snapshots/health/latest` | Latest health snapshot per device |
| GET | `/v1/health/checks` | Per-check and probe results (filterable) |
| GET | `/v1/snapshots/compliance/latest` | Latest compliance snapshot per device |
| GET | `/v1/compliance/controls` | Per-control PASS/FAIL results (filterable) |

### Query parameters

`/v1/health/checks` — `hostname`, `check_name`, `status`, `since` (ISO 8601)

`/v1/compliance/controls` — `hostname`, `control_status` (`PASS` or `FAIL`), `since` (ISO 8601)

### Authentication

Set `API_KEY` in the environment or in `api/.env`. Power BI sends it as the `X-API-Key` request header. Leave unset to disable auth for local development.

### Interactive docs

`http://<host>:8000/docs` — Swagger UI with live try-it-out for all endpoints.

### Connecting Power BI

Use **Get Data → Web** and enter the endpoint URL. Add the `X-API-Key` header under **Advanced** options if auth is enabled.

## Notes

- The export script is backward-compatible with older reports that store CPU and memory metrics as strings.
- This layer is ready for dashboarding now; button-triggered remediation should be added later as a separate approval-controlled workflow.