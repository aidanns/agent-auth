# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/pip_audit_to_sarif.py.

The converter is the hinge between pip-audit's JSON report and the
GitHub Security tab: if it emits malformed SARIF the upload silently
rejects it and advisories stay hidden. These tests drive the script as
a CLI (argv in, files out) to pin down the SARIF envelope shape and
vulnerability mapping.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
CONVERTER = REPO_ROOT / "scripts" / "pip_audit_to_sarif.py"


def _run(tmp_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    in_path = tmp_path / "audit.json"
    out_path = tmp_path / "audit.sarif"
    in_path.write_text(json.dumps(report))
    result = subprocess.run(
        [sys.executable, str(CONVERTER), str(in_path), str(out_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(out_path.read_text()))


def test_empty_report_emits_valid_sarif_envelope(tmp_path):
    sarif = _run(tmp_path, {"dependencies": []})
    assert sarif["version"] == "2.1.0"
    assert sarif["$schema"].endswith("sarif-2.1.0.json")
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "pip-audit"
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []


def test_vulnerability_becomes_result_and_rule(tmp_path):
    report = {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.0.0",
                "vulns": [
                    {
                        "id": "GHSA-xxxx-yyyy-zzzz",
                        "description": "SSRF via proxy",
                        "fix_versions": ["2.32.0"],
                    }
                ],
            }
        ]
    }
    sarif = _run(tmp_path, report)
    run = sarif["runs"][0]

    rules = run["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == ["GHSA-xxxx-yyyy-zzzz"]
    assert "requests" in rules[0]["shortDescription"]["text"]
    assert rules[0]["fullDescription"]["text"] == "SSRF via proxy"
    assert rules[0]["helpUri"].endswith("GHSA-xxxx-yyyy-zzzz")

    assert len(run["results"]) == 1
    result = run["results"][0]
    assert result["ruleId"] == "GHSA-xxxx-yyyy-zzzz"
    assert result["level"] == "error"
    msg = result["message"]["text"]
    assert "requests 2.0.0" in msg
    assert "GHSA-xxxx-yyyy-zzzz" in msg
    # Operators scanning the alert need the fix version surfaced inline;
    # without it they'd have to click through to the rule to learn what
    # to upgrade to.
    assert "2.32.0" in msg
    loc = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert loc == "requirements.txt"


def test_multiple_vulns_across_packages_each_produce_result(tmp_path):
    report = {
        "dependencies": [
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "vulns": [
                    {"id": "GHSA-1", "description": "d1", "fix_versions": ["1.1"]},
                    {"id": "GHSA-2", "description": "d2", "fix_versions": []},
                ],
            },
            {
                "name": "pkg-b",
                "version": "2.0.0",
                "vulns": [
                    {"id": "GHSA-3", "description": "d3", "fix_versions": ["2.1"]},
                ],
            },
        ]
    }
    sarif = _run(tmp_path, report)
    run = sarif["runs"][0]
    rule_ids = sorted(r["id"] for r in run["tool"]["driver"]["rules"])
    assert rule_ids == ["GHSA-1", "GHSA-2", "GHSA-3"]
    result_ids = sorted(r["ruleId"] for r in run["results"])
    assert result_ids == ["GHSA-1", "GHSA-2", "GHSA-3"]


def test_missing_fix_versions_produces_clear_message(tmp_path):
    # Without this guard the converter would emit "upgrade to ." which
    # looks like garbage in the Security tab and loses actionability.
    report = {
        "dependencies": [
            {
                "name": "pkg-x",
                "version": "1.0.0",
                "vulns": [{"id": "GHSA-aaa", "fix_versions": []}],
            }
        ]
    }
    sarif = _run(tmp_path, report)
    result = sarif["runs"][0]["results"][0]
    assert "no fixed version" in result["message"]["text"].lower()


def test_dep_with_no_vulns_emits_no_results(tmp_path):
    report = {
        "dependencies": [
            {"name": "pkg-clean", "version": "1.0.0", "vulns": []},
        ]
    }
    sarif = _run(tmp_path, report)
    assert sarif["runs"][0]["results"] == []
    assert sarif["runs"][0]["tool"]["driver"]["rules"] == []


def test_duplicate_vuln_id_coalesces_rule_but_keeps_each_result(tmp_path):
    # Two dependencies affected by the same advisory should produce one
    # rule (deduplicated) but one result per affected dependency, so the
    # Security tab shows both packages as alerts.
    report = {
        "dependencies": [
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "vulns": [{"id": "GHSA-dup", "description": "shared"}],
            },
            {
                "name": "pkg-b",
                "version": "2.0.0",
                "vulns": [{"id": "GHSA-dup", "description": "shared"}],
            },
        ]
    }
    sarif = _run(tmp_path, report)
    run = sarif["runs"][0]
    assert len(run["tool"]["driver"]["rules"]) == 1
    assert len(run["results"]) == 2


def test_bad_argv_exits_nonzero(tmp_path):
    result = subprocess.run(
        [sys.executable, str(CONVERTER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_missing_input_file_raises(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(CONVERTER),
            str(tmp_path / "does-not-exist.json"),
            str(tmp_path / "out.sarif"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
