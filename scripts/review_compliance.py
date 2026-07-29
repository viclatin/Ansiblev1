import json
import os
from pathlib import Path

import ollama

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
MODEL = os.getenv("OLLAMA_MODEL", "llama3")


def resolve_latest_report(suffix, fallback_name):
    all_matches = [
        path for path in REPORTS_DIR.iterdir()
        if path.is_file() and path.name.endswith(suffix)
    ]

    preferred_fragments = ["victor-switch", "victors-switch", "victor", "switch"]
    for fragment in preferred_fragments:
        matches = [
            path for path in all_matches
            if fragment.lower() in path.name.lower()
        ]
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)

    matches = sorted(all_matches, key=lambda path: path.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]

    fallback = REPORTS_DIR / fallback_name
    if fallback.exists():
        return fallback

    raise FileNotFoundError(f"No report matching *{suffix} found in {REPORTS_DIR}")


REPORT_FILE = resolve_latest_report("_compliance.json", "192.168.1.90_compliance.json")

with open(REPORT_FILE, "r", encoding="utf-8") as handle:
    report = json.load(handle)

prompt = f"""
You are a Senior Cisco Enterprise Network Architect.

Analyze this compliance report.

Do not speculate or assume facts not present.

Return:

- Compliance Summary
- Risk Level
- Failed Controls
- Recommended Actions
- Remediation Priority

Focus on operational network impacts.

Compliance Report:

{json.dumps(report, indent=2)}
"""

try:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )
    content = response.get("message", {}).get("content", "")
except Exception as exc:
    raise RuntimeError(f"Failed to query Ollama model '{MODEL}': {exc}") from exc

print("\n")
print("=" * 60)
print("AI COMPLIANCE ASSESSMENT")
print("=" * 60)
print(content)
print("=" * 60)