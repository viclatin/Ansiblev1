#!/usr/bin/env python3
"""Build a Markdown production deployment summary from repository evidence.

The script only reads repository data and test evidence. It does not execute
or generate configuration on any device.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = ROOT / "group_vars" / "remediation_catalog.yml"
DEFAULT_CHANGES_DIR = ROOT / "changes"


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _find_change_manifest(change_id: str, changes_dir: Path) -> tuple[Path, dict[str, Any]]:
    for manifest_path in sorted(changes_dir.glob("*.yml")):
        manifest = _load_yaml(manifest_path)
        if isinstance(manifest, dict) and manifest.get("change_id") == change_id:
            return manifest_path, manifest
    raise FileNotFoundError(f"No change manifest found for change_id {change_id!r} in {changes_dir}")


def _load_catalog(catalog_path: Path) -> dict[str, Any]:
    catalog_doc = _load_yaml(catalog_path)
    if not isinstance(catalog_doc, dict) or "remediation_catalog" not in catalog_doc:
        raise ValueError(f"{catalog_path} missing remediation_catalog")
    catalog = catalog_doc["remediation_catalog"]
    if not isinstance(catalog, dict):
        raise ValueError("remediation_catalog must be a mapping")
    return catalog


def _extract_ios_config_lines(playbook_path: Path) -> list[str]:
    playbook_doc = _load_yaml(playbook_path)
    if not isinstance(playbook_doc, list):
        raise ValueError(f"{playbook_path} must contain a YAML playbook list")

    for play in playbook_doc:
        if not isinstance(play, dict):
            continue
        tasks = play.get("tasks", [])
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            module_args = task.get("cisco.ios.ios_config")
            if isinstance(module_args, dict):
                lines = module_args.get("lines", [])
                if isinstance(lines, list):
                    return [str(line) for line in lines]
    raise ValueError(f"{playbook_path} does not contain cisco.ios.ios_config lines")


def _format_lines(lines: list[str], prefix: str = "+ ") -> str:
    if not lines:
        return "(none)"
    return "\n".join(f"{prefix}{line}" for line in lines)


def _format_diff(title: str, lines: list[str]) -> str:
    rendered = _format_lines(lines)
    return f"## {title}\n\n```diff\n{rendered}\n```\n"


def _format_current_section(current_config_text: str | None) -> str:
    if current_config_text is None:
        return (
            "## Current production configuration section\n\n"
            "Current production configuration is not captured in this approval step yet.\n"
            "Capture it in the protected production job before remediation is applied.\n"
        )
    return f"## Current production configuration section\n\n```text\n{current_config_text.rstrip()}\n```\n"


def _drift_status(current_lines: list[str] | None, intended_lines: list[str]) -> str:
    if current_lines is None:
        return "PENDING_PRODUCTION_PRECHECK"
    return "DRIFT_DETECTED" if current_lines != intended_lines else "NO_DRIFT"


def _diff_for_lines(before: list[str] | None, after: list[str]) -> str:
    before_lines = before or []
    diff_lines = list(difflib.unified_diff(before_lines, after, fromfile="current", tofile="intended", lineterm=""))
    if diff_lines:
        return "\n".join(diff_lines)
    if before is None:
        return "\n".join(f"+ {line}" for line in after)
    return "(no differences)"


def build_summary(
    change_id: str,
    commit_sha: str,
    test_result_path: Path,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    changes_dir: Path = DEFAULT_CHANGES_DIR,
    current_production_config_path: Path | None = None,
) -> str:
    test_result = _load_json(test_result_path)
    manifest_path, manifest = _find_change_manifest(change_id, changes_dir)
    catalog = _load_catalog(catalog_path)

    remediation = manifest.get("remediation", {})
    if not isinstance(remediation, dict):
        raise ValueError(f"{manifest_path} remediation must be a mapping")

    implementation = manifest.get("implementation", {})
    if not isinstance(implementation, dict):
        raise ValueError(f"{manifest_path} implementation must be a mapping")

    remediation_id = str(remediation.get("remediation_id", ""))
    if remediation_id not in catalog:
        raise KeyError(f"remediation_id {remediation_id!r} not found in catalog")

    catalog_entry = catalog[remediation_id]
    playbook_path = ROOT / str(catalog_entry["playbook"])
    validation_playbook_path = ROOT / str(catalog_entry["validation_playbook"])
    rollback_playbook_path = ROOT / str(catalog_entry["rollback_playbook"])

    intended_lines = _extract_ios_config_lines(playbook_path)
    rollback_lines = _extract_ios_config_lines(rollback_playbook_path)

    current_lines: list[str] | None = None
    current_text: str | None = None
    if current_production_config_path is not None:
        current_text = current_production_config_path.read_text(encoding="utf-8")
        current_lines = [line.strip() for line in current_text.splitlines() if line.strip()]

    drift_status = _drift_status(current_lines, intended_lines)
    intended_diff = _diff_for_lines(current_lines, intended_lines)

    lines: list[str] = []
    lines.append("# Production Deployment Summary")
    lines.append("")
    lines.append(f"- Change ID: `{change_id}`")
    lines.append(f"- Tested commit SHA: `{commit_sha}`")
    lines.append(f"- Control: `{manifest['finding']['control']}`")
    lines.append(f"- Remediation ID: `{remediation_id}`")
    lines.append(f"- Implementation playbook: `{implementation['playbook']}`")
    lines.append(f"- Validation playbook: `{implementation['validation_playbook']}`")
    lines.append(f"- Rollback playbook: `{implementation['rollback_playbook']}`")
    lines.append(f"- Test result: `{test_result.get('test_status', 'UNKNOWN')}`")
    lines.append(f"- Test validation status: `{test_result.get('validation_status', 'UNKNOWN')}`")
    lines.append(f"- Production target allowlist: `{', '.join(catalog_entry.get('production_target_allowlist', []))}`")
    lines.append("")
    lines.append(_format_diff("Original proposed configuration diff", intended_lines))
    lines.append(_format_current_section(current_text))
    lines.append("## Intended production diff\n")
    lines.append("```diff")
    lines.append(intended_diff)
    lines.append("```\n")
    lines.append(f"## Drift status\n\n`{drift_status}`\n")
    lines.append(_format_diff("Rollback plan", rollback_lines))
    lines.append("## Notes\n")
    lines.append("- This summary is generated from repository evidence and test artifacts only.")
    lines.append("- Production approval should use the exact tested commit SHA and protected environment gates.")
    lines.append(f"- Test result artifact: `{test_result_path}`")
    lines.append(f"- Change manifest: `{manifest_path}`")
    lines.append(f"- Rollback tested: `{test_result.get('rollback_tested', False)}`")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Markdown production deployment summary.")
    parser.add_argument("--change-id", required=True, help="Approved change identifier")
    parser.add_argument("--commit-sha", required=True, help="Exact tested commit SHA")
    parser.add_argument("--test-result", required=True, type=Path, help="Path to the test result JSON artifact")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH, help="Path to remediation catalogue")
    parser.add_argument("--changes-dir", type=Path, default=DEFAULT_CHANGES_DIR, help="Directory containing change manifests")
    parser.add_argument(
        "--current-production-config",
        type=Path,
        default=None,
        help="Optional path to captured current production configuration text",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_summary(
        change_id=args.change_id,
        commit_sha=args.commit_sha,
        test_result_path=args.test_result,
        catalog_path=args.catalog,
        changes_dir=args.changes_dir,
        current_production_config_path=args.current_production_config,
    )
    print(summary, end="")


if __name__ == "__main__":
    main()
