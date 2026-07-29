import json
import subprocess
from pathlib import Path


PROJECT_DIR = Path.home() / "ansible"
INVENTORY_FILE = PROJECT_DIR / "inventories" / "cisco.ini"
PLAYBOOK_DIR = PROJECT_DIR / "playbooks"
REPORT_DIR = PROJECT_DIR / "reports"
BACKUP_DIR = PROJECT_DIR / "backups"


REMEDIATION_CATALOG = {
    "AAA": {
        "playbook": "remediation/remediate_aaa.yml",
        "report_pattern": "*_aaa_remediation.json",
    },
    "NTP": {
        "playbook": "remediation/remediate_ntp.yml",
        "report_pattern": "*_ntp_remediation.json",
    },
    "SNMP": {
        "playbook": "remediation/remediate_snmp.yml",
        "report_pattern": "*_snmp_remediation.json",
    },
    "SYSLOG": {
        "playbook": "remediation/remediate_syslog.yml",
        "report_pattern": "*_syslog_remediation.json",
    },
    "SSH": {
        "playbook": "remediation/remediate_ssh.yml",
        "report_pattern": "*_ssh_remediation.json",
    },
    "HTTP": {
        "playbook": "remediation/remediate_http.yml",
        "report_pattern": "*_http_remediation.json",
    },
}


def run_playbook(playbook_name: str) -> str:
    """
    Execute an Ansible playbook and return the execution summary.

    Raises RuntimeError when the playbook fails.
    """

    command = [
        "ansible-playbook",
        "-i",
        str(INVENTORY_FILE),
        str(PLAYBOOK_DIR / playbook_name),
    ]

    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Playbook {playbook_name} failed.\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}"
        )

    return result.stdout


def get_latest_report(report_pattern: str) -> Path:
    """Find the newest report matching the supplied filename pattern."""

    matching_reports = list(REPORT_DIR.glob(report_pattern))

    if not matching_reports:
        raise FileNotFoundError(
            f"No report matching '{report_pattern}' was found in "
            f"{REPORT_DIR}"
        )

    return max(
        matching_reports,
        key=lambda report: report.stat().st_mtime,
    )


def load_json_report(report_pattern: str) -> dict:
    """Load the newest JSON report matching the filename pattern."""

    report_file = get_latest_report(report_pattern)

    with report_file.open("r", encoding="utf-8") as file:
        report_data = json.load(file)

    return {
        "report_file": str(report_file),
        "report_data": report_data,
    }


def run_compliance() -> str:
    """
    Run the compliance playbook and return the resulting compliance JSON.
    """

    run_playbook("compliance.yml")

    report = load_json_report("*_compliance.json")

    return json.dumps(
        {
            "workflow": "compliance_assessment",
            "execution_status": "SUCCESS",
            **report,
        },
        indent=2,
    )


def run_health() -> str:
    """
    Run the health-check playbook and return the resulting health JSON.
    """

    run_playbook("healthcheck.yml")

    report = load_json_report("*_health.json")

    return json.dumps(
        {
            "workflow": "health_assessment",
            "execution_status": "SUCCESS",
            **report,
        },
        indent=2,
    )


def run_backup() -> str:
    """
    Run the configuration-backup playbook and return backup metadata.
    """

    run_playbook("backup.yml")

    backup_files = [
        {
            "filename": file.name,
            "path": str(file),
            "size_bytes": file.stat().st_size,
        }
        for file in BACKUP_DIR.glob("*")
        if file.is_file()
    ]

    return json.dumps(
        {
            "workflow": "configuration_backup",
            "execution_status": "SUCCESS",
            "backup_files": backup_files,
        },
        indent=2,
    )


def get_remediation_catalog() -> dict:
    """Return supported compliance control -> remediation playbook mappings."""

    return REMEDIATION_CATALOG


def run_remediation(control_name: str) -> str:
    """
    Run a control-specific remediation playbook and return its JSON report.

    Raises ValueError if the control has no mapped remediation playbook.
    Raises RuntimeError when the remediation playbook fails.
    """

    normalized = str(control_name).strip().upper()
    control = REMEDIATION_CATALOG.get(normalized)
    if control is None:
        supported = ", ".join(sorted(REMEDIATION_CATALOG.keys()))
        raise ValueError(
            f"Unsupported remediation control '{control_name}'. "
            f"Supported controls: {supported}."
        )

    run_playbook(control["playbook"])
    report = load_json_report(control["report_pattern"])

    return json.dumps(
        {
            "workflow": "control_remediation",
            "control_name": normalized,
            "playbook": control["playbook"],
            "execution_status": "SUCCESS",
            **report,
        },
        indent=2,
    )