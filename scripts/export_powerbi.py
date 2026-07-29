"""Build Power BI-friendly flat exports from the latest switch reports.

This keeps the raw Ansible JSON reports unchanged while producing
curated CSV tables that are easier to model in Power BI.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
DEFAULT_OUTPUT_DIR = REPORTS_DIR / "powerbi"
SCHEMA_VERSION = "1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export flattened Power BI tables from switch health and compliance reports."
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Directory containing the raw JSON reports.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the CSV exports should be written.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def coerce_cpu_output(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    text = normalize_text(value)
    if not text:
        return {}

    used_match = re.search(r"five seconds:\s*(\d+)%/(\d+)%", text, flags=re.IGNORECASE)
    one_minute_match = re.search(r"one minute:\s*(\d+)%", text, flags=re.IGNORECASE)
    five_minutes_match = re.search(r"five minutes:\s*(\d+)%", text, flags=re.IGNORECASE)

    return {
        "five_seconds_used_percent": int(used_match.group(1)) if used_match else None,
        "five_seconds_idle_percent": int(used_match.group(2)) if used_match else None,
        "one_minute_percent": int(one_minute_match.group(1)) if one_minute_match else None,
        "five_minutes_percent": int(five_minutes_match.group(1)) if five_minutes_match else None,
    }


def coerce_memory_output(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    text = normalize_text(value)
    if not text:
        return {}

    processor_match = re.search(
        r"^Processor\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)",
        text,
        flags=re.MULTILINE,
    )
    if not processor_match:
        return {}

    total_bytes = int(processor_match.group(1))
    used_bytes = int(processor_match.group(2))
    free_bytes = int(processor_match.group(3))
    used_percent = round((used_bytes / total_bytes) * 100, 2) if total_bytes else None

    return {
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "used_percent": used_percent,
    }


def parse_probe_metrics(probe_data: Any) -> tuple[Any, str]:
    if not isinstance(probe_data, dict):
        return None, "unknown"

    avg = probe_data.get("rtt_avg_ms")
    try:
        avg_ms = float(avg)
    except (TypeError, ValueError):
        avg_ms = None

    band = normalize_text(probe_data.get("latency_band", "")).lower()
    if band in {"low", "medium", "high", "unclassified"}:
        return avg_ms, band

    if avg_ms is None:
        return None, "unknown"
    if avg_ms <= 30:
        return avg_ms, "low"
    if 60 <= avg_ms <= 100:
        return avg_ms, "medium"
    if avg_ms >= 120:
        return avg_ms, "high"
    return avg_ms, "unclassified"


def parse_interface_summary(interfaces_output: str) -> dict[str, int]:
    rows = [line for line in interfaces_output.splitlines() if line.strip()]
    if len(rows) <= 1:
        return {"interfaces_up": 0, "interfaces_admin_down": 0, "interfaces_other": 0}

    up = 0
    admin_down = 0
    other = 0

    for line in rows[1:]:
        text = line.lower()
        if " administratively down" in text:
            admin_down += 1
        elif re.search(r"\bup\b\s+\bup\b", text):
            up += 1
        else:
            other += 1

    return {
        "interfaces_up": up,
        "interfaces_admin_down": admin_down,
        "interfaces_other": other,
    }


def build_health_snapshot(report_file: Path, report_data: dict[str, Any]) -> dict[str, Any]:
    cpu_output = coerce_cpu_output(report_data.get("cpu_output", {}))
    memory_output = coerce_memory_output(report_data.get("memory_output", {}))
    checks = report_data.get("checks", {}) or {}
    probe_checks = checks.get("probes", {}) or {}
    ntp_check = checks.get("ntp", {}) or {}
    interface_check = checks.get("interface_errors", {}) or {}
    ping_8_8_8_8 = probe_checks.get("ping_8_8_8_8", {})
    ping_8_8_4_4 = probe_checks.get("ping_8_8_4_4", {})
    ping_8_8_8_8_avg, ping_8_8_8_8_band = parse_probe_metrics(ping_8_8_8_8)
    ping_8_8_4_4_avg, ping_8_8_4_4_band = parse_probe_metrics(ping_8_8_4_4)

    probe_failures = 0
    for probe_data in probe_checks.values():
        if isinstance(probe_data, dict):
            status = normalize_text(probe_data.get("status")).lower()
            if status and status not in {"ok", "not_applicable", "not_supported"}:
                probe_failures += 1

    interface_summary = parse_interface_summary(normalize_text(report_data.get("interfaces_output", "")))
    ntp_raw = normalize_text(ntp_check.get("raw_output", "")).lower()

    return {
        "source_file": str(report_file),
        "report_type": "health",
        "hostname": normalize_text(report_data.get("hostname", "")),
        "timestamp": normalize_text(report_data.get("timestamp", "")),
        "ios_version": normalize_text(report_data.get("ios_version", "")),
        "overall_status": _derive_health_overall_status(checks, ntp_raw, probe_failures),
        "operational_risk": _derive_health_risk(checks, ntp_raw, probe_failures),
        "cpu_5s_used_percent": cpu_output.get("five_seconds_used_percent"),
        "cpu_1m_percent": cpu_output.get("one_minute_percent"),
        "cpu_5m_percent": cpu_output.get("five_minutes_percent"),
        "memory_used_percent": memory_output.get("used_percent"),
        "memory_free_bytes": memory_output.get("free_bytes"),
        "interface_errors_status": normalize_text(interface_check.get("status", "")),
        "ntp_status": normalize_text(ntp_check.get("status", "")),
        "ntp_unsynchronized": "yes" if "unsynchronized" in ntp_raw else "no",
        "probe_failures": probe_failures,
        "ping_8_8_8_8_latency_avg_ms": ping_8_8_8_8_avg,
        "ping_8_8_8_8_latency_band": ping_8_8_8_8_band,
        "ping_8_8_4_4_latency_avg_ms": ping_8_8_4_4_avg,
        "ping_8_8_4_4_latency_band": ping_8_8_4_4_band,
        **interface_summary,
    }


def _derive_health_overall_status(checks: dict[str, Any], ntp_raw: str, probe_failures: int) -> str:
    warning_checks = 0
    high_severity_checks = {"interface_errors", "power_and_fans", "environmental_status"}

    for check_name, check_data in checks.items():
        if check_name == "probes" or not isinstance(check_data, dict):
            continue
        if normalize_text(check_data.get("status", "")).lower() == "warning":
            if check_name in high_severity_checks:
                return "CRITICAL_ATTENTION_REQUIRED"
            warning_checks += 1

    if "unsynchronized" in ntp_raw or probe_failures > 0:
        return "DEGRADED"
    if warning_checks:
        return "ATTENTION_REQUIRED"
    return "HEALTHY"


def _derive_health_risk(checks: dict[str, Any], ntp_raw: str, probe_failures: int) -> str:
    for check_name, check_data in checks.items():
        if check_name == "probes" or not isinstance(check_data, dict):
            continue
        if normalize_text(check_data.get("status", "")).lower() == "warning" and check_name in {
            "interface_errors",
            "power_and_fans",
            "environmental_status",
        }:
            return "High"

    if "unsynchronized" in ntp_raw or probe_failures > 0:
        return "Medium"
    if any(
        normalize_text(check.get("status", "")).lower() == "warning"
        for name, check in checks.items()
        if name != "probes" and isinstance(check, dict)
    ):
        return "Medium"
    return "Low"


def build_health_check_rows(report_file: Path, report_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hostname = normalize_text(report_data.get("hostname", ""))
    timestamp = normalize_text(report_data.get("timestamp", ""))
    checks = report_data.get("checks", {}) or {}

    for check_name, check_data in checks.items():
        if check_name == "probes" and isinstance(check_data, dict):
            for probe_name, probe_data in check_data.items():
                if isinstance(probe_data, dict):
                    probe_avg, probe_band = parse_probe_metrics(probe_data)
                    rows.append(
                        {
                            "source_file": str(report_file),
                            "report_type": "health",
                            "hostname": hostname,
                            "timestamp": timestamp,
                            "section": "probe",
                            "check_name": probe_name,
                            "status": normalize_text(probe_data.get("status", "")),
                            "latency_avg_ms": probe_avg,
                            "latency_band": probe_band,
                            "details": normalize_text(probe_data.get("raw_output", ""))[:2000],
                        }
                    )
                else:
                    rows.append(
                        {
                            "source_file": str(report_file),
                            "report_type": "health",
                            "hostname": hostname,
                            "timestamp": timestamp,
                            "section": "probe",
                            "check_name": probe_name,
                            "status": "not_applicable",
                            "latency_avg_ms": "",
                            "latency_band": "",
                            "details": normalize_text(probe_data)[:2000],
                        }
                    )
            continue

        if isinstance(check_data, dict):
            rows.append(
                {
                    "source_file": str(report_file),
                    "report_type": "health",
                    "hostname": hostname,
                    "timestamp": timestamp,
                    "section": "check",
                    "check_name": check_name,
                    "status": normalize_text(check_data.get("status", "")),
                    "latency_avg_ms": "",
                    "latency_band": "",
                    "details": normalize_text(check_data.get("details", "")),
                }
            )

    return rows


def build_compliance_snapshot(report_file: Path, report_data: dict[str, Any]) -> dict[str, Any]:
    results = report_data.get("results", {}) or {}
    failed_controls = report_data.get("failed_controls", []) or []
    passed_controls = report_data.get("passed_controls", []) or []

    return {
        "source_file": str(report_file),
        "report_type": "compliance",
        "hostname": normalize_text(report_data.get("hostname", "")),
        "timestamp": normalize_text(report_data.get("timestamp", "")),
        "compliance_score": report_data.get("compliance_score"),
        "compliance_status": normalize_text(report_data.get("compliance_status", "")),
        "total_controls": report_data.get("total_controls"),
        "passed_controls_count": len(passed_controls),
        "failed_controls_count": len(failed_controls),
        "controls_evaluated_count": len(results),
        "compliance_risk": _derive_compliance_risk(report_data.get("compliance_score")),
    }


def _derive_compliance_risk(score: Any) -> str:
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return "Unknown"

    if numeric_score >= 90:
        return "Low"
    if numeric_score >= 70:
        return "Medium"
    return "High"


def build_compliance_control_rows(report_file: Path, report_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hostname = normalize_text(report_data.get("hostname", ""))
    timestamp = normalize_text(report_data.get("timestamp", ""))
    score = report_data.get("compliance_score")
    compliance_status = normalize_text(report_data.get("compliance_status", ""))
    results = report_data.get("results", {}) or {}

    for control_name, control_status in results.items():
        rows.append(
            {
                "source_file": str(report_file),
                "report_type": "compliance",
                "hostname": hostname,
                "timestamp": timestamp,
                "control_name": control_name,
                "control_status": normalize_text(control_status),
                "compliance_score": score,
                "compliance_status": compliance_status,
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    reports_dir = args.reports_dir.resolve()
    output_dir = args.output_dir.resolve()
    generated_at = datetime.now(timezone.utc).isoformat()

    health_reports = sorted(reports_dir.glob("*_health.json"))
    compliance_reports = sorted(reports_dir.glob("*_compliance.json"))

    health_snapshots: list[dict[str, Any]] = []
    health_check_rows: list[dict[str, Any]] = []
    compliance_snapshots: list[dict[str, Any]] = []
    compliance_control_rows: list[dict[str, Any]] = []

    for report_file in health_reports:
        report_data = load_json(report_file)
        health_snapshots.append(build_health_snapshot(report_file, report_data))
        health_check_rows.extend(build_health_check_rows(report_file, report_data))

    for report_file in compliance_reports:
        report_data = load_json(report_file)
        compliance_snapshots.append(build_compliance_snapshot(report_file, report_data))
        compliance_control_rows.extend(build_compliance_control_rows(report_file, report_data))

    write_csv(
        output_dir / "device_health_snapshots.csv",
        health_snapshots,
        [
            "source_file",
            "report_type",
            "hostname",
            "timestamp",
            "ios_version",
            "overall_status",
            "operational_risk",
            "cpu_5s_used_percent",
            "cpu_1m_percent",
            "cpu_5m_percent",
            "memory_used_percent",
            "memory_free_bytes",
            "interfaces_up",
            "interfaces_admin_down",
            "interfaces_other",
            "interface_errors_status",
            "ntp_status",
            "ntp_unsynchronized",
            "probe_failures",
            "ping_8_8_8_8_latency_avg_ms",
            "ping_8_8_8_8_latency_band",
            "ping_8_8_4_4_latency_avg_ms",
            "ping_8_8_4_4_latency_band",
        ],
    )

    write_csv(
        output_dir / "health_checks.csv",
        health_check_rows,
        [
            "source_file",
            "report_type",
            "hostname",
            "timestamp",
            "section",
            "check_name",
            "status",
            "latency_avg_ms",
            "latency_band",
            "details",
        ],
    )

    write_csv(
        output_dir / "compliance_snapshots.csv",
        compliance_snapshots,
        [
            "source_file",
            "report_type",
            "hostname",
            "timestamp",
            "compliance_score",
            "compliance_status",
            "total_controls",
            "passed_controls_count",
            "failed_controls_count",
            "controls_evaluated_count",
            "compliance_risk",
        ],
    )

    write_csv(
        output_dir / "compliance_controls.csv",
        compliance_control_rows,
        [
            "source_file",
            "report_type",
            "hostname",
            "timestamp",
            "control_name",
            "control_status",
            "compliance_score",
            "compliance_status",
        ],
    )

    write_json(
        output_dir / "export_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "reports_dir": str(reports_dir),
            "tables": [
                {
                    "name": "device_health_snapshots",
                    "file": "device_health_snapshots.csv",
                    "row_count": len(health_snapshots),
                },
                {
                    "name": "health_checks",
                    "file": "health_checks.csv",
                    "row_count": len(health_check_rows),
                },
                {
                    "name": "compliance_snapshots",
                    "file": "compliance_snapshots.csv",
                    "row_count": len(compliance_snapshots),
                },
                {
                    "name": "compliance_controls",
                    "file": "compliance_controls.csv",
                    "row_count": len(compliance_control_rows),
                },
            ],
        },
    )

    print(f"Exported {len(health_snapshots)} health snapshots to {output_dir}")
    print(f"Exported {len(health_check_rows)} health check rows to {output_dir}")
    print(f"Exported {len(compliance_snapshots)} compliance snapshots to {output_dir}")
    print(f"Exported {len(compliance_control_rows)} compliance control rows to {output_dir}")
    print(f"Wrote export manifest to {output_dir / 'export_manifest.json'}")


if __name__ == "__main__":
    main()