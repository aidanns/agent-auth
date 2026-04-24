#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Build a Dependency Graph snapshot from .github/tool-versions.yaml and
# POST it to /repos/{owner}/{repo}/dependency-graph/snapshots so
# Dependabot Alerts can ingest CVEs for every pinned CI tool. See
# ADR 0031 and issue #205.
#
# Called from .github/workflows/dependency-submission.yml. Expects the
# usual GitHub Actions env (GITHUB_REPOSITORY, GITHUB_SHA, GITHUB_REF,
# GITHUB_RUN_ID, GITHUB_WORKFLOW, GITHUB_JOB, GITHUB_TOKEN) and
# MANIFEST_PATH pointing at .github/tool-versions.yaml.

set -euo pipefail

: "${GITHUB_REPOSITORY:?must be set}"
: "${GITHUB_SHA:?must be set}"
: "${GITHUB_REF:?must be set}"
: "${GITHUB_RUN_ID:?must be set}"
: "${GITHUB_WORKFLOW:?must be set}"
: "${GITHUB_JOB:?must be set}"
: "${GITHUB_TOKEN:?must be set}"
: "${MANIFEST_PATH:?must be set}"

if [[ ! -f "${MANIFEST_PATH}" ]]; then
  echo "submit-dependency-snapshot: ${MANIFEST_PATH} is missing" >&2
  exit 1
fi

payload="$(
  MANIFEST="${MANIFEST_PATH}" python3 <<'PY'
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# Map manifest key -> PURL template. ${VERSION} is substituted with the
# manifest's version value. Prefixing with "v" where the upstream GitHub
# release tag is prefixed keeps the PURL pointing at the exact release
# object GitHub advisories reference. Tools pinned by manifest entries
# like systems-engineering (ref, not version) are intentionally left
# out — no upstream ecosystem indexes their advisories.
PURL_TEMPLATES = {
    "shellcheck":       "pkg:github/koalaman/shellcheck@v${VERSION}",
    "shfmt":            "pkg:github/mvdan/sh@v${VERSION}",
    "ruff":             "pkg:github/astral-sh/ruff@${VERSION}",
    "taplo":            "pkg:github/tamasfe/taplo@${VERSION}",
    "keep-sorted":      "pkg:github/google/keep-sorted@v${VERSION}",
    "ripsecrets":       "pkg:github/sirwart/ripsecrets@v${VERSION}",
    "treefmt":          "pkg:github/numtide/treefmt@v${VERSION}",
    "go-task":          "pkg:github/go-task/task@v${VERSION}",
    "d2":               "pkg:github/terrastruct/d2@v${VERSION}",
    "uv":               "pkg:github/astral-sh/uv@${VERSION}",
    "mdformat":         "pkg:pypi/mdformat@${VERSION}",
    "mdformat-gfm":     "pkg:pypi/mdformat-gfm@${VERSION}",
    "mdformat-tables":  "pkg:pypi/mdformat-tables@${VERSION}",
}


def read_manifest(path: Path) -> dict[str, dict]:
    # Tiny flat-YAML parser — avoids a pyyaml dependency on the runner.
    # The manifest is hand-edited and every tool block is:
    #     <key>:
    #       version: "X.Y.Z"      # or similar
    #       sha256_linux_x86_64: "..."
    tools: dict[str, dict] = {}
    current: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == line.lstrip():
            # Top-level key: `tool-name:` (no leading whitespace).
            m = re.match(r"^([A-Za-z0-9_-]+):\s*$", line)
            current = m.group(1) if m else None
            if current:
                tools[current] = {}
            continue
        if current is None:
            continue
        m = re.match(r'^\s+([A-Za-z0-9_-]+):\s*"([^"]*)"\s*$', line)
        if m:
            tools[current][m.group(1)] = m.group(2)
    return tools


manifest_path = Path(os.environ["MANIFEST"])
tools = read_manifest(manifest_path)

resolved: dict[str, dict] = {}
skipped: list[str] = []
for key, template in PURL_TEMPLATES.items():
    entry = tools.get(key)
    version = (entry or {}).get("version")
    if not version:
        skipped.append(key)
        continue
    purl = template.replace("${VERSION}", version)
    resolved[key] = {"package_url": purl}

if skipped:
    print(
        f"submit-dependency-snapshot: manifest has no version for: {', '.join(skipped)}",
        file=sys.stderr,
    )

snapshot = {
    "version": 0,
    "sha": os.environ["GITHUB_SHA"],
    "ref": os.environ["GITHUB_REF"],
    "job": {
        "id": os.environ["GITHUB_RUN_ID"],
        "correlator": f"{os.environ['GITHUB_WORKFLOW']}/{os.environ['GITHUB_JOB']}",
    },
    "detector": {
        "name": "tool-versions-manifest",
        "version": "1.0.0",
        "url": "https://github.com/aidanns/agent-auth/blob/main/.github/tool-versions.yaml",
    },
    "scanned": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "manifests": {
        "tool-versions": {
            "name": "tool-versions",
            "file": {"source_location": str(manifest_path)},
            "resolved": resolved,
        },
    },
}
print(json.dumps(snapshot))
PY
)"

echo "Submitting snapshot with $(echo "${payload}" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["manifests"]["tool-versions"]["resolved"]))') resolved packages."

http_status="$(
  curl -sS -o /tmp/snapshot-response.json -w "%{http_code}" \
    -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Content-Type: application/json" \
    --data @- \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/dependency-graph/snapshots" <<<"${payload}"
)"

if [[ ! "${http_status}" =~ ^20[0-9]$ && ! "${http_status}" =~ ^201$ ]]; then
  echo "submit-dependency-snapshot: POST returned ${http_status}" >&2
  cat /tmp/snapshot-response.json >&2
  exit 1
fi

echo "submit-dependency-snapshot: POST OK (${http_status})"
cat /tmp/snapshot-response.json
