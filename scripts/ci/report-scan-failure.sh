#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Open, comment on, or close a GitHub issue tracking the state of a
# scheduled security scan (pip-audit today, Trivy when #88 lands). One
# open issue per (repo, label) tuple is the dedupe contract: if the
# scheduled job fails and an open issue already carries the label we
# append a comment with the new run-url and sha instead of opening a
# duplicate; if the job succeeds and an open issue exists we close it
# with a recovery comment so the signal tracks reality.
#
# Usage:
#   report-scan-failure.sh <status> <label> <title> <sha> <run-url>
#     status    : "failed" | "succeeded"
#     label     : dedupe label (e.g. "pip-audit-failure")
#     title     : issue title used when opening a new failure issue
#     sha       : commit sha the scan ran against
#     run-url   : link to the failed/recovering workflow run
#
# Requires: gh authenticated via GH_TOKEN / GITHUB_TOKEN with
# `issues: write` on the target repo.

set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "report-scan-failure: expected 5 args (status, label, title, sha, run-url); got $#" >&2
  exit 2
fi

status="$1"
label="$2"
title="$3"
sha="$4"
run_url="$5"

case "${status}" in
  failed | succeeded) ;;
  *)
    echo "report-scan-failure: unknown status '${status}' (expected 'failed' or 'succeeded')" >&2
    exit 2
    ;;
esac

# Return the number of the single open issue carrying the dedupe label,
# or empty string if none. --limit 1 is enough because the invariant is
# at most one open issue per label.
existing=$(gh issue list \
  --state open \
  --label "${label}" \
  --limit 1 \
  --json number \
  --jq '.[0].number // ""')

if [[ "${status}" == "failed" ]]; then
  body=$(printf 'Scheduled scan failed.\n\n- Commit: %s\n- Run: %s\n' "${sha}" "${run_url}")
  if [[ -n "${existing}" ]]; then
    echo "report-scan-failure: commenting on existing issue #${existing}" >&2
    gh issue comment "${existing}" --body "${body}"
  else
    echo "report-scan-failure: opening new failure issue with label '${label}'" >&2
    gh issue create \
      --title "${title}" \
      --label "${label}" \
      --body "${body}"
  fi
else
  if [[ -n "${existing}" ]]; then
    body=$(printf 'Scheduled scan recovered.\n\n- Commit: %s\n- Run: %s\n' "${sha}" "${run_url}")
    echo "report-scan-failure: closing recovered issue #${existing}" >&2
    gh issue comment "${existing}" --body "${body}"
    gh issue close "${existing}"
  else
    echo "report-scan-failure: no open issue to close for label '${label}'" >&2
  fi
fi
