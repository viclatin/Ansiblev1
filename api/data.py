"""Load and filter the Power BI export files.

All reads are at request time so Power BI always gets the freshest data
after the Ansible playbooks run and export_powerbi.py is executed.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _safe_path(data_dir: Path, filename: str) -> Path:
    """Resolve a filename strictly inside data_dir to prevent path traversal."""
    resolved = (data_dir / filename).resolve()
    if not resolved.is_relative_to(data_dir.resolve()):
        raise ValueError(f"Unsafe path: {filename}")
    return resolved


def load_manifest(data_dir: Path) -> dict[str, Any]:
    path = _safe_path(data_dir, "export_manifest.json")
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_csv(data_dir: Path, filename: str) -> list[dict[str, Any]]:
    path = _safe_path(data_dir, filename)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def latest_per_hostname(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the most recent row for each hostname (by timestamp string desc)."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        host = row.get("hostname", "")
        ts = row.get("timestamp", "")
        if host not in best or ts > best[host].get("timestamp", ""):
            best[host] = row
    return list(best.values())


def filter_rows(
    rows: list[dict[str, Any]],
    hostname: str | None = None,
    status: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    result = rows
    if hostname:
        hostname_lower = hostname.lower()
        result = [r for r in result if r.get("hostname", "").lower() == hostname_lower]
    if status:
        status_lower = status.lower().strip()
        result = [r for r in result if r.get("status", "").lower().strip() == status_lower]
    if since:
        result = [r for r in result if r.get("timestamp", "") >= since]
    return result
