from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parents[1]
CHANGES_DIR = PROJECT_DIR / "changes"
REPORT_DIR = PROJECT_DIR / "reports"
CATALOG_PATH = PROJECT_DIR / "group_vars" / "remediation_catalog.yml"
LOCAL_GH_PATH = Path.home() / ".local" / "bin" / "gh"


def _run(command: list[str], *, cwd: Path = PROJECT_DIR) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed: " + " ".join(command) + "\n\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result


def _ensure_gh_available() -> None:
    if _resolve_gh_executable() is None:
        raise RuntimeError(
            "GitHub CLI missing. Install 'gh' and authenticate before using GitHub workflow helpers."
        )


def _resolve_gh_executable() -> str | None:
    gh_path = shutil.which("gh")
    if gh_path:
        return gh_path
    if LOCAL_GH_PATH.exists():
        return str(LOCAL_GH_PATH)
    return None


def _gh_command(*args: str) -> list[str]:
    gh_executable = _resolve_gh_executable()
    if gh_executable is None:
        raise RuntimeError(
            "GitHub CLI missing. Install 'gh' and authenticate before using GitHub workflow helpers."
        )
    return [gh_executable, *args]


def _ensure_gh_authenticated() -> None:
    _ensure_gh_available()
    _run(_gh_command("auth", "status"))


def _load_catalog() -> dict[str, Any]:
    catalog_doc = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(catalog_doc, dict) or "remediation_catalog" not in catalog_doc:
        raise ValueError("remediation_catalog.yml missing remediation_catalog")
    catalog = catalog_doc["remediation_catalog"]
    if not isinstance(catalog, dict):
        raise ValueError("remediation_catalog must be a mapping")
    return catalog


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def _current_branch() -> str:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = result.stdout.strip()
    return branch if branch and branch != "HEAD" else "main"


def _latest_report(patterns: list[str]) -> Path:
    matching: list[Path] = []
    for pattern in patterns:
        matching.extend(REPORT_DIR.glob(pattern))
    files = [path for path in matching if path.is_file()]
    if not files:
        raise FileNotFoundError(f"No report found matching {patterns}")
    return max(files, key=lambda path: path.stat().st_mtime)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _remediation_report_payload(control: str, hostname: str) -> tuple[Path, dict[str, Any]]:
    report_path = _latest_report([f"*{hostname}*compliance.json", "*_compliance.json"])
    report_doc = _load_json(report_path)
    report_data = report_doc.get("report_data", report_doc)
    if not isinstance(report_data, dict):
        report_data = {}
    return report_path, report_data


def _extract_control_status(report_data: dict[str, Any], control: str) -> str:
    results = report_data.get("results")
    if isinstance(results, dict):
        for key, value in results.items():
            if str(key).strip().upper() != control:
                continue
            if isinstance(value, dict):
                status = value.get("status")
            else:
                status = value
            if status is not None:
                return str(status).strip().upper()

    fallback = report_data.get("compliance_status", report_data.get("status"))
    if fallback is None:
        return "UNKNOWN"
    return str(fallback).strip().upper()


def _build_change_id(control: str, hostname: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"CHG-{_slugify(control).upper()}-{_slugify(hostname).upper()}-{timestamp}"


def _render_change_manifest(
    *,
    change_id: str,
    hostname: str,
    control: str,
    remediation_id: str,
    evidence_report: Path,
    compliance_score: Any,
    current_status: str,
    playbook: str,
    validation_playbook: str,
    rollback_playbook: str,
    production_target_allowlist: list[str],
) -> dict[str, Any]:
    return {
        "change_id": change_id,
        "status": "PROPOSED",
        "requested_by": "network-agent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": {
            "hostname": hostname,
            "test_inventory_group": "remediation_targets",
            "production_inventory_group": production_target_allowlist[0],
        },
        "finding": {
            "control": control,
            "current_status": current_status,
            "compliance_score": compliance_score,
            "evidence_report": str(evidence_report.relative_to(PROJECT_DIR)),
        },
        "remediation": {
            "remediation_id": remediation_id,
            "justification": "Proposal generated from current compliance evidence",
        },
        "implementation": {
            "playbook": playbook,
            "validation_playbook": validation_playbook,
            "rollback_playbook": rollback_playbook,
        },
        "promotion": {
            "test_required": True,
            "production_approval_required": True,
            "production_status": "NOT_AUTHORIZED",
        },
    }


def propose_remediation(hostname: str, control: str, remediation_id: str) -> str:
    """
    Create a feature branch, write a change manifest, push the branch,
    and open a GitHub pull request.

    This function does not merge the pull request and does not execute
    any Ansible remediation.
    """

    _ensure_gh_authenticated()

    normalized_control = str(control).strip().upper()
    catalog = _load_catalog()
    entry = catalog.get(remediation_id)
    if entry is None:
        supported = ", ".join(sorted(catalog.keys()))
        raise ValueError(f"Unknown remediation_id '{remediation_id}'. Supported IDs: {supported}.")

    if str(entry.get("control", "")).strip().upper() != normalized_control:
        raise ValueError(
            f"remediation_id '{remediation_id}' maps to control '{entry.get('control')}', not '{control}'."
        )

    change_id = _build_change_id(normalized_control, hostname)
    branch_name = f"agent/remediation/{_slugify(change_id)}"
    evidence_report, report_data = _remediation_report_payload(normalized_control, hostname)
    base_branch = "main"

    change_manifest = _render_change_manifest(
        change_id=change_id,
        hostname=hostname,
        control=normalized_control,
        remediation_id=remediation_id,
        evidence_report=evidence_report,
        compliance_score=report_data.get("compliance_score", "unknown"),
        current_status=_extract_control_status(report_data, normalized_control),
        playbook=str(entry["playbook"]),
        validation_playbook=str(entry["validation_playbook"]),
        rollback_playbook=str(entry["rollback_playbook"]),
        production_target_allowlist=list(entry.get("production_target_allowlist", ["production_canary_switches"])),
    )

    manifest_path = CHANGES_DIR / f"{change_id}.yml"
    if manifest_path.exists():
        raise FileExistsError(f"Change manifest already exists: {manifest_path}")

    _run(["git", "checkout", "-b", branch_name])
    manifest_path.write_text(yaml.safe_dump(change_manifest, sort_keys=False), encoding="utf-8")
    _run(["git", "add", str(manifest_path.relative_to(PROJECT_DIR))])
    _run(["git", "commit", "-m", f"Propose remediation {change_id}"])
    _run(["git", "push", "-u", "origin", branch_name])

    pr_result = _run(
        _gh_command(
            "pr",
            "create",
            "--title",
            f"[Remediation] {change_id} {normalized_control}",
            "--body",
            (
                f"Change proposal for {hostname}.\n\n"
                f"This PR only proposes remediation. It does not merge or execute Ansible remediation.\n"
                f"Remediation ID: {remediation_id}\n"
                f"Evidence report: {evidence_report.relative_to(PROJECT_DIR)}\n"
            ),
            "--head",
            branch_name,
            "--base",
            base_branch,
        )
    )

    pr_url = pr_result.stdout.strip()
    pr_view = _run(_gh_command("pr", "view", branch_name, "--json", "number,state,url"))
    pr_data = json.loads(pr_view.stdout or "{}")
    pr_number = pr_data.get("number")
    pr_state = pr_data.get("state", "OPEN")

    lines = [
        f"Selected remediation: {remediation_id}",
        f"Pull request created: #{pr_number if pr_number is not None else 'unknown'}",
        f"Status: PENDING_PEER_REVIEW" if pr_state == "OPEN" else f"Status: {pr_state}",
        "No device changes have been executed.",
        "Configuration changed: false",
        f"Change ID: {change_id}",
        f"Branch: {branch_name}",
        f"Pull request URL: {pr_url or pr_data.get('url', 'unknown')}",
    ]
    return "\n".join(lines)


def get_change_status(change_id: str) -> str:
    _ensure_gh_authenticated()

    manifest_path = CHANGES_DIR / f"{change_id}.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path} must contain a YAML mapping")

    test_result_path = REPORT_DIR / f"test-result-{change_id}.json"
    test_result = _load_json(test_result_path) if test_result_path.exists() else None

    pr_query = _run(
        _gh_command(
            "pr",
            "list",
            "--search",
            change_id,
            "--json",
            "number,title,url,state",
        )
    )
    pull_requests = json.loads(pr_query.stdout or "[]")

    status_lines = [f"Change ID: {change_id}"]
    status_lines.append(f"Manifest status: {manifest.get('status', 'unknown')}")
    if test_result is not None:
        status_lines.append(f"Test status: {test_result.get('test_status', 'unknown')}")
        status_lines.append(f"Validation status: {test_result.get('validation_status', 'unknown')}")
    else:
        status_lines.append("Test status: unknown")
        status_lines.append("Validation status: unknown")
    if pull_requests:
        first_pr = pull_requests[0]
        status_lines.append(f"Pull request: #{first_pr.get('number', 'unknown')} ({first_pr.get('state', 'unknown')})")
    else:
        status_lines.append("Pull request: none found")

    status_lines.append("No configuration has been changed.")
    return "\n".join(status_lines)


def request_test_deployment(change_id: str, commit_sha: str) -> str:
    _ensure_gh_authenticated()

    _run(
        _gh_command(
            "workflow",
            "run",
            ".github/workflows/deploy-test.yml",
            "--ref",
            _current_branch(),
            "--field",
            f"change_id={change_id}",
            "--field",
            f"commit_sha={commit_sha}",
        )
    )

    return "\n".join(
        [
            f"Change ID: {change_id}",
            f"Test deployment requested for commit SHA: {commit_sha}",
            "Workflow: deploy-test",
            "Status: REQUESTED",
            "No configuration has been changed.",
        ]
    )


def request_production_promotion(
    change_id: str,
    commit_sha: str,
    test_run_id: str,
    target_group: str = "production_canary_switches",
) -> str:
    _ensure_gh_authenticated()

    _run(
        _gh_command(
            "workflow",
            "run",
            ".github/workflows/deploy-production.yml",
            "--ref",
            _current_branch(),
            "--field",
            f"change_id={change_id}",
            "--field",
            f"commit_sha={commit_sha}",
            "--field",
            f"test_run_id={test_run_id}",
            "--field",
            f"target_group={target_group}",
        )
    )

    return "\n".join(
        [
            f"Change ID: {change_id}",
            f"Production promotion requested for exact tested SHA: {commit_sha}",
            f"Test run ID: {test_run_id}",
            f"Target group: {target_group}",
            "Workflow: deploy-production",
            "Status: REQUESTED",
            "No configuration has been changed.",
        ]
    )