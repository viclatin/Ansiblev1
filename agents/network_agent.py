import os
import sys
import json
import re
from typing import List

# PydanticAI uses Ollama's OpenAI-compatible API endpoint.
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")

try:
    from pydantic_ai import Agent
except ModuleNotFoundError:
    import sys
    sys.stderr.write(
        "\nMissing dependency: 'pydantic_ai' not installed in this Python environment.\n"
        "Run the agent using the project virtualenv, for example:\n"
        "  cd /home/victor/ansible && /home/victor/ansible/scripts/venv/bin/python -m agents.network_agent\n"
        "Or install the package into the current environment:\n"
        "  python -m pip install pydantic-ai\n\n"
    )
    raise

try:
    from .prompts import SYSTEM_PROMPT
    from .tools import (
        run_backup,
        run_compliance,
        run_health,
        get_remediation_catalog,
    )
    from .github_tools import (
        propose_remediation as _propose_remediation,
        get_change_status as _get_change_status,
        request_test_deployment as _request_test_deployment,
        request_production_promotion as _request_production_promotion,
    )
except ImportError:  # pragma: no cover - script execution fallback
    from prompts import SYSTEM_PROMPT
    from tools import (
        run_backup,
        run_compliance,
        run_health,
        get_remediation_catalog,
    )
    from github_tools import (
        propose_remediation as _propose_remediation,
        get_change_status as _get_change_status,
        request_test_deployment as _request_test_deployment,
        request_production_promotion as _request_production_promotion,
    )


# Create the PydanticAI agent.
agent = Agent(
    "ollama:qwen3:8b",
    system_prompt=SYSTEM_PROMPT,
)


# Register Ansible workflows as agent tools.

@agent.tool_plain
def compliance() -> str:
    """Run the Cisco IOS-XE compliance assessment workflow."""
    return run_compliance()


@agent.tool_plain
def health() -> str:
    """Run the Cisco IOS-XE operational health assessment workflow."""
    return run_health()


@agent.tool_plain
def backup() -> str:
    """Run the Cisco IOS-XE configuration backup workflow."""
    return run_backup()


def _is_remediation_intent(text: str) -> bool:
    """Detect operator intent to run guided remediation workflows."""
    normalized = text.lower().strip()
    if not normalized:
        return False

    explicit_phrases = [
        "remediate",
        "remediation",
        "fix compliance",
        "approve remediation",
        "fix remaining",
        "remaining failed",
        "remaining failures",
        "fix failed control",
        "fix failed controls",
    ]
    if any(phrase in normalized for phrase in explicit_phrases):
        return True

    # Direct control actions such as "fix http now" should trigger remediation.
    control_tokens = set(get_remediation_catalog().keys())
    tokens = set(re.findall(r"[a-z]+", normalized))
    if (tokens & {"fix", "remediate", "resolve", "apply"}) and (tokens & {t.lower() for t in control_tokens}):
        return True

    has_fix_word = bool(tokens & {"fix", "remediate", "resolve"})
    has_failure_word = bool(tokens & {"failed", "failure", "failures", "remaining"})
    has_control_word = bool(tokens & {"control", "controls", "compliance"})
    return has_fix_word and has_failure_word and has_control_word


def _extract_control_hints(text: str) -> List[str]:
    """Extract remediation control names explicitly mentioned in user input."""
    normalized = text.lower().strip()
    if not normalized:
        return []

    token_set = set(re.findall(r"[a-z]+", normalized))
    catalog = get_remediation_catalog()
    mentioned = [control for control in sorted(catalog.keys()) if control.lower() in token_set]
    return mentioned


def _extract_remediation_id(text: str) -> str | None:
    match = re.search(r"\b(REM-[A-Z]+-\d+)\b", text.upper())
    return match.group(1) if match else None


def _extract_hostname_hint(text: str) -> str | None:
    match = re.search(r"\bon\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


@agent.tool_plain
def propose_remediation(hostname: str, control: str, remediation_id: str) -> str:
    """Create a remediation proposal PR from repository-controlled evidence."""
    return _propose_remediation(hostname=hostname, control=control, remediation_id=remediation_id)


@agent.tool_plain
def get_change_status(change_id: str) -> str:
    """Return the current repository and workflow status for a change proposal."""
    return _get_change_status(change_id=change_id)


@agent.tool_plain
def request_test_deployment(change_id: str, commit_sha: str) -> str:
    """Request the GitHub Actions test deployment workflow."""
    return _request_test_deployment(change_id=change_id, commit_sha=commit_sha)


@agent.tool_plain
def request_production_promotion(
    change_id: str,
    commit_sha: str,
    test_run_id: str,
    target_group: str = "production_canary_switches",
) -> str:
    """Request the GitHub Actions production promotion workflow."""
    return _request_production_promotion(
        change_id=change_id,
        commit_sha=commit_sha,
        test_run_id=test_run_id,
        target_group=target_group,
    )


def _parse_interface_status(interfaces_output: str) -> dict:
    rows = [line for line in interfaces_output.splitlines() if line.strip()]
    if len(rows) <= 1:
        return {"up": 0, "admin_down": 0, "other": 0, "total": 0}

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

    total = up + admin_down + other
    return {"up": up, "admin_down": admin_down, "other": other, "total": total}


def _parse_interface_error_counters(raw_output: str) -> dict:
    input_errors = [int(value) for value in re.findall(r"(\d+)\s+input errors", raw_output)]
    output_errors = [int(value) for value in re.findall(r"(\d+)\s+output errors", raw_output)]
    crc_errors = [int(value) for value in re.findall(r"(\d+)\s+CRC", raw_output)]
    if not input_errors and not output_errors and not crc_errors:
        return {"parsed": False, "input_errors": 0, "output_errors": 0, "crc_errors": 0}

    return {
        "parsed": True,
        "input_errors": sum(input_errors),
        "output_errors": sum(output_errors),
        "crc_errors": sum(crc_errors),
    }


def _parse_probe_telemetry(probes: dict) -> list:
    telemetry = []
    for target in ["ping_8_8_8_8", "ping_8_8_4_4"]:
        probe = probes.get(target)
        if not isinstance(probe, dict):
            continue
        raw = str(probe.get("raw_output", ""))
        success_match = re.search(r"Success rate is\s+(\d+)\s+percent", raw, flags=re.IGNORECASE)
        rtt_match = re.search(r"round-trip min/avg/max\s*=\s*\d+/(\d+)/\d+\s*ms", raw, flags=re.IGNORECASE)
        if success_match:
            success = int(success_match.group(1))
            rtt_text = f", avg RTT {rtt_match.group(1)} ms" if rtt_match else ""
            telemetry.append(f"- {target.replace('ping_', 'Ping ').replace('_', '.')} success: {success}%{rtt_text}")

    for target in ["traceroute_8_8_8_8", "traceroute_8_8_4_4"]:
        raw = probes.get(target)
        if not isinstance(raw, str):
            continue
        hop_lines = re.findall(r"^\s*\d+\s+.+$", raw, flags=re.MULTILINE)
        reached = "dns.google" in raw.lower() or "(8.8.8.8)" in raw or "(8.8.4.4)" in raw
        if hop_lines:
            status = "reached destination" if reached else "did not clearly reach destination"
            label = target.replace("traceroute_", "Traceroute ").replace("_", ".")
            telemetry.append(f"- {label}: {len(hop_lines)} hops observed, {status}")

    return telemetry


def _format_compliance_summary(raw_result: str) -> str:
    payload = json.loads(raw_result)
    report = payload.get("report_data", {})
    hostname = report.get("hostname", "unknown")
    score = report.get("compliance_score", "unknown")
    status = report.get("compliance_status", "unknown")
    passed = report.get("passed_controls", []) or []
    failed = report.get("failed_controls", []) or []
    total = report.get("total_controls", len(report.get("results", {})))

    if isinstance(score, (int, float)):
        if score >= 90:
            risk = "Low"
        elif score >= 70:
            risk = "Medium"
        else:
            risk = "High"
    else:
        risk = "Unknown"

    recommendation_lines = []
    if failed:
        for control in failed:
            recommendation_lines.append(f"- Remediate failed control: {control}")
        recommendation_lines.append("- Re-run compliance assessment after remediation")
    else:
        recommendation_lines.append("- No immediate action required")

    return "\n".join([
        "DEVICE",
        f"- Hostname: {hostname}",
        "- Workflow: compliance_assessment",
        f"- Execution status: {payload.get('execution_status', 'unknown')}",
        "",
        "OBSERVED FINDINGS",
        f"- Compliance score: {score}/100",
        f"- Compliance status: {status}",
        f"- Passed controls ({len(passed)}): {', '.join(passed) if passed else 'none'}",
        f"- Failed controls ({len(failed)}): {', '.join(failed) if failed else 'none'}",
        f"- Total controls evaluated: {total}",
        "",
        "ASSESSMENT",
        f"- Overall status: {status}",
        f"- Operational risk: {risk}",
        "- Confidence: High (structured compliance data parsed successfully)",
        "",
        "RECOMMENDATIONS",
        *recommendation_lines,
        "",
        "DATA LIMITATIONS",
        "- None",
    ])


def _format_health_summary(raw_result: str) -> str:
    payload = json.loads(raw_result)
    report = payload.get("report_data", {})
    hostname = report.get("hostname", "unknown")
    cpu = report.get("cpu_output", {}) or {}
    memory = report.get("memory_output", {}) or {}
    checks = report.get("checks", {}) or {}
    interfaces_output = str(report.get("interfaces_output", ""))

    severity_map = {
        "interface_errors": "high",
        "power_and_fans": "high",
        "environmental_status": "high",
        "bgp_neighbors": "medium",
        "ospf_neighbors": "medium",
        "spanning_tree": "medium",
        "logging_events": "low",
        "inventory": "low",
        "stack_state": "low",
        "ntp": "medium",
    }

    warning_checks = []
    warning_by_severity = {"high": [], "medium": [], "low": []}
    failed_probes = []
    informational_notes = []
    for check_name, check_data in checks.items():
        if check_name == "probes" and isinstance(check_data, dict):
            for probe_name, probe_data in check_data.items():
                if isinstance(probe_data, dict):
                    probe_status = _normalize_status(probe_data.get("status"))
                    if probe_status not in {"ok", "not_applicable", "not_supported"}:
                        failed_probes.append(probe_name)
            continue

        status = _normalize_status(check_data.get("status") if isinstance(check_data, dict) else "unknown")
        if status == "warning":
            warning_checks.append(check_name)
            severity = severity_map.get(check_name, "medium")
            warning_by_severity[severity].append(check_name)
    # Override potentially noisy check statuses using raw network evidence.
    interface_check = checks.get("interface_errors")
    if isinstance(interface_check, dict):
        counters = _parse_interface_error_counters(str(interface_check.get("raw_output", "")))
        if counters["parsed"]:
            total_errors = counters["input_errors"] + counters["output_errors"] + counters["crc_errors"]
            if total_errors == 0 and "interface_errors" in warning_checks:
                warning_checks.remove("interface_errors")
                warning_by_severity["high"] = [item for item in warning_by_severity["high"] if item != "interface_errors"]
                informational_notes.append("- Interface error counters are clean (0 input/CRC/output errors)")
            elif total_errors > 0:
                informational_notes.append(
                    "- Interface counters show errors "
                    f"(input={counters['input_errors']}, crc={counters['crc_errors']}, output={counters['output_errors']})"
                )

    bgp_check = checks.get("bgp_neighbors")
    if isinstance(bgp_check, dict):
        bgp_raw = str(bgp_check.get("raw_output", ""))
        if "bgp not active" in bgp_raw.lower() and "bgp_neighbors" in warning_checks:
            warning_checks.remove("bgp_neighbors")
            warning_by_severity["medium"] = [item for item in warning_by_severity["medium"] if item != "bgp_neighbors"]
            informational_notes.append("- BGP is not configured/active on this device (treated as informational)")

    ntp_raw = ""
    ntp_data = checks.get("ntp")
    if isinstance(ntp_data, dict):
        ntp_raw = str(ntp_data.get("raw_output", ""))
    ntp_unsynced = "unsynchronized" in ntp_raw.lower()

    cpu_used = cpu.get("five_seconds_used_percent")
    memory_used = memory.get("used_percent")
    iface_state = _parse_interface_status(interfaces_output)

    probes = checks.get("probes")
    probe_telemetry = _parse_probe_telemetry(probes if isinstance(probes, dict) else {})

    findings = []
    if cpu_used is not None:
        findings.append(f"- CPU (5-second used): {cpu_used}%")
    if memory_used is not None:
        findings.append(f"- Memory used: {memory_used}%")
    if iface_state["total"] > 0:
        findings.append(
            "- Interface state summary: "
            f"{iface_state['up']} up, {iface_state['admin_down']} administratively down, {iface_state['other']} other"
        )
    if warning_by_severity["high"]:
        findings.append(f"- High severity warnings: {', '.join(sorted(warning_by_severity['high']))}")
    if warning_by_severity["medium"]:
        findings.append(f"- Medium severity warnings: {', '.join(sorted(warning_by_severity['medium']))}")
    if warning_by_severity["low"]:
        findings.append(f"- Low severity warnings: {', '.join(sorted(warning_by_severity['low']))}")
    if ntp_unsynced:
        findings.append("- NTP clock is unsynchronized")
    if failed_probes:
        findings.append(f"- Connectivity probe issues: {', '.join(sorted(failed_probes))}")
    findings.extend(probe_telemetry)
    findings.extend(informational_notes)
    if not findings:
        findings.append("- No major health exceptions detected in parsed fields")

    if warning_by_severity["high"]:
        risk = "High"
        overall = "CRITICAL_ATTENTION_REQUIRED"
    elif failed_probes or ntp_unsynced:
        risk = "Medium"
        overall = "DEGRADED"
    elif warning_checks:
        risk = "Medium"
        overall = "ATTENTION_REQUIRED"
    else:
        risk = "Low"
        overall = "HEALTHY"

    recommendations = []
    if ntp_unsynced:
        recommendations.append("- Configure and verify reachable NTP servers")
    if failed_probes:
        recommendations.append("- Investigate upstream reachability for failed probes")
    if warning_by_severity["high"]:
        recommendations.append("- Triage high-severity warning checks immediately")
    elif warning_checks:
        recommendations.append("- Review warning checks and validate expected state")
    if not recommendations:
        recommendations.append("- No immediate action required")

    # Hide expected unsupported/not_applicable checks by default to reduce noise.
    limitations = ["- None"]

    return "\n".join([
        "DEVICE",
        f"- Hostname: {hostname}",
        "- Workflow: health_assessment",
        f"- Execution status: {payload.get('execution_status', 'unknown')}",
        "",
        "OBSERVED FINDINGS",
        *findings,
        "",
        "ASSESSMENT",
        f"- Overall status: {overall}",
        f"- Operational risk: {risk}",
        "- Confidence: High (structured health report parsed successfully)",
        "",
        "RECOMMENDATIONS",
        *recommendations,
        "",
        "DATA LIMITATIONS",
        *limitations,
    ])


def _format_backup_summary(raw_result: str) -> str:
    payload = json.loads(raw_result)
    files = payload.get("backup_files", []) or []
    file_count = len(files)
    latest = files[-1]["filename"] if files else "none"
    return "\n".join([
        "DEVICE",
        "- Hostname: from inventory target",
        "- Workflow: configuration_backup",
        f"- Execution status: {payload.get('execution_status', 'unknown')}",
        "",
        "OBSERVED FINDINGS",
        f"- Backup files available: {file_count}",
        f"- Most recent backup file listed: {latest}",
        "",
        "ASSESSMENT",
        "- Overall status: SUCCESS" if payload.get("execution_status") == "SUCCESS" else "- Overall status: UNKNOWN",
        "- Operational risk: Low",
        "- Confidence: High (backup metadata returned by workflow)",
        "",
        "RECOMMENDATIONS",
        "- Periodically restore-test backup files",
        "",
        "DATA LIMITATIONS",
        "- None",
    ])


def _parse_failed_controls(raw_compliance_result: str) -> List[str]:
    payload = json.loads(raw_compliance_result)
    report = payload.get("report_data", {}) or {}
    failed = report.get("failed_controls", []) or []
    return [str(item).strip().upper() for item in failed if str(item).strip()]


def _offer_remediation_after_compliance(raw_compliance_result: str, interactive: bool) -> bool:
    """Optionally offer immediate guided remediation after a failed compliance run."""
    if not interactive:
        return False

    failed_controls = _parse_failed_controls(raw_compliance_result)
    if not failed_controls:
        return False

    print("\nCompliance found failed controls: " + ", ".join(failed_controls))
    while True:
        answer = input("Start guided remediation now? [yes/no]: ").strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("Please answer yes or no.")


def _select_remediation_scope(failed_controls: List[str], interactive: bool) -> List[str]:
    """Collect operator-selected controls (single, multiple, all, or none)."""
    if not failed_controls:
        return []
    if not interactive:
        return []

    available = sorted(set(failed_controls))
    print("\nSelect controls to remediate now.")
    print("- Available failed controls: " + ", ".join(available))
    print("- Enter one control (example: NTP), multiple controls (example: NTP,HTTP), 'all', or 'none'.")

    while True:
        answer = input("Controls to remediate: ").strip().upper()
        if answer in {"NONE", "N"}:
            return []
        if answer in {"ALL", "A", "BOTH"}:
            return available

        selected = [item.strip() for item in answer.split(",") if item.strip()]
        if not selected:
            print("Please enter at least one control, 'all', or 'none'.")
            continue

        invalid = [item for item in selected if item not in available]
        if invalid:
            print("Unsupported selection: " + ", ".join(invalid))
            print("Choose only from: " + ", ".join(available))
            continue

        deduped = []
        for item in selected:
            if item not in deduped:
                deduped.append(item)
        return deduped


def _build_remediation_plan_summary(selected_controls: List[str], catalog: dict) -> str:
    lines = [
        "\nProposed remediation plan:",
        f"- Controls selected: {', '.join(selected_controls) if selected_controls else 'none'}",
    ]
    for control in selected_controls:
        mapped = catalog.get(control)
        if mapped is None:
            lines.append(f"- {control}: no mapped playbook")
        else:
            lines.append(f"- {control}: playbooks/{mapped['playbook']}")
    lines.append("- Post-change action: re-run compliance validation")
    return "\n".join(lines)


def _confirm_remediation_plan(interactive: bool) -> bool:
    if not interactive:
        return False
    while True:
        answer = input("Approve and execute this remediation plan? [yes/no]: ").strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("Please answer yes or no.")


def _recommend_remediation_playbooks(failed_controls: List[str]) -> List[str]:
    catalog = get_remediation_catalog()
    recommendations = []
    for control in failed_controls:
        mapped = catalog.get(control)
        if mapped is None:
            recommendations.append(f"- {control}: no remediation playbook mapped")
        else:
            recommendations.append(
                f"- {control}: playbooks/{mapped['playbook']}"
            )
    return recommendations


def _collect_engineer_approvals(failed_controls: List[str], interactive: bool) -> List[str]:
    if not failed_controls:
        return []
    if not interactive:
        return []

    approved = []
    print("\nEngineer approval required before remediation execution.")
    print("Reply yes/no per control, or type 'all' / 'none'.")

    for control in failed_controls:
        while True:
            answer = input(f"Approve remediation for {control}? [yes/no/all/none]: ").strip().lower()
            if answer in {"all", "a"}:
                return failed_controls
            if answer in {"none", "n"}:
                return []
            if answer in {"yes", "y"}:
                approved.append(control)
                break
            if answer in {"no"}:
                break
            print("Please answer yes, no, all, or none.")

    return approved


def _format_remediation_execution_summary(results: List[dict], revalidation_raw: str) -> str:
    revalidation_payload = json.loads(revalidation_raw)
    report = revalidation_payload.get("report_data", {}) or {}
    score = report.get("compliance_score", "unknown")
    status = report.get("compliance_status", "unknown")
    failed = report.get("failed_controls", []) or []

    lines = [
        "DEVICE",
        f"- Hostname: {report.get('hostname', 'unknown')}",
        "- Workflow: guided_compliance_remediation",
        "- Execution status: SUCCESS",
        "",
        "OBSERVED FINDINGS",
    ]

    if results:
        for item in results:
            lines.append(
                f"- {item['control']}: {item['status']} ({item['playbook']})"
            )
    else:
        lines.append("- No remediation playbooks were approved for execution")

    lines.extend([
        f"- Re-validation compliance score: {score}/100",
        f"- Re-validation compliance status: {status}",
        f"- Remaining failed controls: {', '.join(failed) if failed else 'none'}",
        "",
        "ASSESSMENT",
        f"- Overall status: {status}",
        "- Operational risk: Low" if not failed else "- Operational risk: Medium",
        "- Confidence: High (post-change compliance report collected)",
        "",
        "RECOMMENDATIONS",
        "- Continue with normal operations" if not failed else "- Review remaining failed controls and approve targeted remediation",
        "",
        "DATA LIMITATIONS",
        "- None",
    ])

    return "\n".join(lines)


def _format_remediation_cancelled_summary(compliance_raw: str, reason: str) -> str:
    payload = json.loads(compliance_raw)
    report = payload.get("report_data", {}) or {}
    score = report.get("compliance_score", "unknown")
    status = report.get("compliance_status", "unknown")
    failed = report.get("failed_controls", []) or []

    return "\n".join([
        "DEVICE",
        f"- Hostname: {report.get('hostname', 'unknown')}",
        "- Workflow: guided_compliance_remediation",
        "- Execution status: CANCELLED",
        "",
        "OBSERVED FINDINGS",
        f"- Remediation was not executed: {reason}",
        f"- Latest known compliance score: {score}/100",
        f"- Latest known compliance status: {status}",
        f"- Current failed controls: {', '.join(failed) if failed else 'none'}",
        "",
        "ASSESSMENT",
        f"- Overall status: {status}",
        "- Operational risk: Medium" if failed else "- Operational risk: Low",
        "- Confidence: High (no configuration changes applied)",
        "",
        "RECOMMENDATIONS",
        "- Re-run guided remediation when ready to approve changes",
        "",
        "DATA LIMITATIONS",
        "- Post-change re-validation not run because no changes were applied",
    ])


def run_guided_remediation_flow(
    prompt: str,
    interactive: bool,
    compliance_raw: str | None = None,
    preselected_controls: List[str] | None = None,
) -> str:
    """
    Compliance-driven remediation workflow:
    1) Run compliance and detect failed controls.
    2) Recommend mapped remediation playbooks.
    3) Require engineer approval per control.
    4) Run approved remediation playbooks.
    5) Re-run compliance for post-change validation.
    """

    if compliance_raw is None:
        compliance_raw = run_compliance()
    failed_controls = _parse_failed_controls(compliance_raw)
    catalog = get_remediation_catalog()

    if not failed_controls:
        return "\n".join([
            "DEVICE",
            "- Hostname: from latest compliance report",
            "- Workflow: guided_compliance_remediation",
            "- Execution status: SUCCESS",
            "",
            "OBSERVED FINDINGS",
            "- No failed compliance controls detected",
            "",
            "ASSESSMENT",
            "- Overall status: COMPLIANT",
            "- Operational risk: Low",
            "- Confidence: High",
            "",
            "RECOMMENDATIONS",
            "- No immediate action required",
            "",
            "DATA LIMITATIONS",
            "- None",
        ])

    recommendations = _recommend_remediation_playbooks(failed_controls)
    print("\nRecommended remediation playbooks for current compliance failures:")
    for line in recommendations:
        print(line)

    selectable_controls = [control for control in failed_controls if control in catalog]
    hinted_controls = [control for control in (preselected_controls or []) if control in selectable_controls]

    if hinted_controls:
        selected_controls = hinted_controls
        print("\nDetected requested control(s) from command: " + ", ".join(selected_controls))
    elif len(selectable_controls) == 1:
        selected_controls = selectable_controls
        print("\nOnly one failed control is eligible for remediation: " + selected_controls[0])
    else:
        selected_controls = _select_remediation_scope(selectable_controls, interactive=interactive)
    if not selected_controls:
        return _format_remediation_cancelled_summary(
            compliance_raw,
            reason="no controls selected",
        )

    print(_build_remediation_plan_summary(selected_controls, catalog))
    if not _confirm_remediation_plan(interactive=interactive):
        return _format_remediation_cancelled_summary(
            compliance_raw,
            reason="final approval declined",
        )

    print("\nApplying approved remediation playbooks. Please wait...")

    execution_results = []
    for control in selected_controls:
        mapped = catalog[control]
        try:
            remediation_raw = run_remediation(control)
            remediation_payload = json.loads(remediation_raw)
            status = remediation_payload.get("report_data", {}).get("status", "UNKNOWN")
            execution_results.append({
                "control": control,
                "playbook": mapped["playbook"],
                "status": status,
            })
        except Exception as error:  # pragma: no cover - runtime workflow resilience
            execution_results.append({
                "control": control,
                "playbook": mapped["playbook"],
                "status": f"FAILED ({type(error).__name__})",
            })

    revalidation_raw = run_compliance()
    return _format_remediation_execution_summary(execution_results, revalidation_raw)


def handle_direct_request(prompt: str):
    """Route obvious requests directly to the correct workflow."""
    text = prompt.lower().strip()
    if not text:
        return None

    if any(keyword in text for keyword in ["health", "healthcheck"]):
        return _format_health_summary(run_health())

    if _is_remediation_intent(text):
        remediation_id = _extract_remediation_id(prompt)
        hostname = _extract_hostname_hint(prompt)
        control_hints = _extract_control_hints(text)
        control = control_hints[0] if control_hints else None

        if remediation_id and hostname and control:
            try:
                return propose_remediation(hostname=hostname, control=control, remediation_id=remediation_id)
            except Exception as error:  # pragma: no cover - operational fallback
                return "\n".join([
                    "DEVICE",
                    f"- Hostname: {hostname}",
                    "- Workflow: remediation_proposal",
                    "- Execution status: FAILED",
                    "",
                    "OBSERVED FINDINGS",
                    f"- Proposal request failed: {type(error).__name__}: {error}",
                    "",
                    "ASSESSMENT",
                    "- Overall status: PROPOSAL_NOT_CREATED",
                    "- Operational risk: Controlled",
                    "- Confidence: High",
                    "",
                    "RECOMMENDATIONS",
                    "- Confirm gh authentication and repository push permissions",
                    "- Retry with hostname, control, and remediation_id",
                    "",
                    "DATA LIMITATIONS",
                    "- No configuration has been changed",
                ])

        return "\n".join([
            "DEVICE",
            "- Hostname: from change request",
            "- Workflow: remediation_proposal",
            "- Execution status: ROUTED_TO_GIT_WORKFLOW",
            "",
            "OBSERVED FINDINGS",
            "- Remediation intent detected from user input",
            "",
            "ASSESSMENT",
            "- Overall status: PENDING_CHANGE_PROPOSAL",
            "- Operational risk: Controlled",
            "- Confidence: High",
            "",
            "RECOMMENDATIONS",
            "- Use propose_remediation with hostname, control, and remediation_id",
            "- Review and approve via pull request workflow before any deployment",
            "",
            "DATA LIMITATIONS",
            "- No configuration has been changed",
        ])

    if any(keyword in text for keyword in ["compliance", "audit", "policy"]):
        compliance_raw = run_compliance()
        compliance_summary = _format_compliance_summary(compliance_raw)
        interactive = sys.stdin.isatty()
        # Show the complete compliance report first, then optionally start remediation.
        if interactive:
            print("\n" + "=" * 70)
            print(compliance_summary)
            print("=" * 70)
        if _offer_remediation_after_compliance(compliance_raw, interactive=sys.stdin.isatty()):
            return run_guided_remediation_flow(
                prompt,
                interactive=interactive,
                compliance_raw=compliance_raw,
            )
        if interactive:
            return ""
        return compliance_summary

    if any(keyword in text for keyword in ["backup", "save config", "configuration backup"]):
        return _format_backup_summary(run_backup())

    return None


def main() -> None:
    """Start the interactive network operations agent."""

    print("\n" + "=" * 50)
    print("Cisco Network Operations Agent")
    print("=" * 50)
    print("Examples:")
    print("  - Run a compliance assessment")
    print("  - Check switch health")
    print("  - Back up the switch configuration")
    print("  - quit")
    print("=" * 50)

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        try:
            direct_result = handle_direct_request(prompt)
            if direct_result is not None:
                if direct_result:
                    print("\n" + "=" * 70)
                    print(direct_result)
                    print("=" * 70)
                return
            result = agent.run_sync(prompt)
            print("\n" + "=" * 70)
            print(result.output)
            print("=" * 70)
        except KeyboardInterrupt:
            print("\n\nOperation cancelled.")
        except Exception as error:
            print(f"\n[ERROR] {type(error).__name__}: {error}")
        return

    while True:
        command = input("\nNetwork Agent > ").strip()

        if not command:
            continue

        if command.lower() in {"quit", "exit"}:
            print("\nGoodbye.")
            break

        try:
            direct_result = handle_direct_request(command)
            if direct_result is not None:
                if direct_result:
                    print("\n" + "=" * 70)
                    print(direct_result)
                    print("=" * 70)
                continue
            result = agent.run_sync(command)

            print("\n" + "=" * 70)
            print(result.output)
            print("=" * 70)

        except KeyboardInterrupt:
            print("\n\nOperation cancelled.")
            break

        except Exception as error:
            print(f"\n[ERROR] {type(error).__name__}: {error}")


if __name__ == "__main__":
    main()