#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Convert pip-audit JSON output to a minimal SARIF 2.1.0 document.

pip-audit 2.10 does not emit SARIF directly (supported formats:
columns, json, cyclonedx-json, cyclonedx-xml, markdown). The GitHub
Security tab ingests SARIF, so this CLI wraps pip-audit's JSON report
into the smallest valid SARIF envelope that ``codeql-action/upload-sarif``
accepts. Keeping the converter in-tree avoids adding a third-party
SARIF-conversion dependency to the security scanning path.

Usage::

    pip-audit -r requirements.txt --format json --output audit.json
    python scripts/pip_audit_to_sarif.py audit.json audit.sarif
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
TOOL_NAME = "pip-audit"
TOOL_URI = "https://github.com/pypa/pip-audit"
# The requirements file is where pip-audit reads declared deps from;
# SARIF needs a location per finding and this is the only artifact
# the scan inspects. The Security tab renders this as the origin file.
FINDING_LOCATION_URI = "requirements.txt"


def convert(pip_audit_report: dict[str, Any]) -> dict[str, Any]:
    """Build a SARIF 2.1.0 document from a pip-audit ``--format json`` report."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for dep in pip_audit_report.get("dependencies", []) or []:
        pkg_name = dep.get("name", "<unknown>")
        pkg_version = dep.get("version", "<unknown>")
        for vuln in dep.get("vulns") or []:
            vuln_id = vuln.get("id") or "UNKNOWN"
            description = vuln.get("description") or (
                f"{pkg_name} {pkg_version} is affected by {vuln_id}."
            )
            fix_versions = vuln.get("fix_versions") or []
            help_uri = f"https://osv.dev/vulnerability/{vuln_id}"

            rules.setdefault(
                vuln_id,
                {
                    "id": vuln_id,
                    "name": vuln_id,
                    "shortDescription": {"text": f"{vuln_id} in {pkg_name}"},
                    "fullDescription": {"text": description},
                    "helpUri": help_uri,
                },
            )

            fix_note = (
                f"upgrade to {', '.join(fix_versions)}"
                if fix_versions
                else "no fixed version is available yet"
            )
            results.append(
                {
                    "ruleId": vuln_id,
                    "level": "error",
                    "message": {
                        "text": f"{pkg_name} {pkg_version} is vulnerable to {vuln_id}; {fix_note}.",
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": FINDING_LOCATION_URI,
                                },
                            },
                        },
                    ],
                }
            )

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": TOOL_URI,
                        "rules": list(rules.values()),
                    },
                },
                "results": results,
            },
        ],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: pip_audit_to_sarif.py <pip-audit.json> <out.sarif>\n")
        return 2
    in_path = Path(argv[1])
    out_path = Path(argv[2])
    report = json.loads(in_path.read_text())
    sarif = convert(report)
    out_path.write_text(json.dumps(sarif, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
