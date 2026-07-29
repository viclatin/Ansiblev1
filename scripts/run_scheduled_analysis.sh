#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/victor/ansible"
PYTHON="$ROOT/scripts/venv/bin/python"
RUNNER="$ROOT/scripts/scheduled_analysis.py"
LOG_DIR="$ROOT/reports/automation/scheduler-logs"

mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/run_${STAMP}.log"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python runtime not found at $PYTHON" >&2
  exit 1
fi

"$PYTHON" "$RUNNER" >>"$LOG_FILE" 2>&1
