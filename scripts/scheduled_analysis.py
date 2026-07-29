from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
AUTOMATION_DIR = REPORTS_DIR / "automation"
RUNS_DIR = AUTOMATION_DIR / "runs"
VENV_PYTHON = ROOT / "scripts" / "venv" / "bin" / "python"


@dataclass
class StepResult:
    name: str
    command: list[str]
    returncode: int
    started_at: str
    finished_at: str
    stdout_log: str
    stderr_log: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def run_step(name: str, command: list[str], run_dir: Path) -> StepResult:
    started = utc_now()
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    finished = utc_now()

    stdout_log = run_dir / f"{name}.stdout.log"
    stderr_log = run_dir / f"{name}.stderr.log"
    stdout_log.write_text(result.stdout, encoding="utf-8")
    stderr_log.write_text(result.stderr, encoding="utf-8")

    return StepResult(
        name=name,
        command=command,
        returncode=result.returncode,
        started_at=started,
        finished_at=finished,
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def main() -> int:
    run_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)

    py = ensure_python()

    steps: list[tuple[str, list[str]]] = [
        (
            "compliance_playbook",
            ["ansible-playbook", "-i", "inventories/cisco.ini", "playbooks/compliance.yml"],
        ),
        (
            "health_playbook",
            ["ansible-playbook", "-i", "inventories/cisco.ini", "playbooks/healthcheck.yml"],
        ),
        ("powerbi_export", [py, "scripts/export_powerbi.py"]),
    ]

    results: list[StepResult] = []

    for name, command in steps:
        step_result = run_step(name, command, run_dir)
        results.append(step_result)
        if step_result.returncode != 0:
            summary = {
                "status": "failed",
                "run_timestamp": run_ts,
                "failed_step": name,
                "results": [r.__dict__ for r in results],
            }
            write_summary(run_dir / "summary.json", summary)
            write_summary(AUTOMATION_DIR / "latest_run.json", summary)
            print(f"Run failed at step: {name}")
            return step_result.returncode

    summary = {
        "status": "success",
        "run_timestamp": run_ts,
        "results": [r.__dict__ for r in results],
    }
    write_summary(run_dir / "summary.json", summary)
    write_summary(AUTOMATION_DIR / "latest_run.json", summary)

    print("Scheduled analysis completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
