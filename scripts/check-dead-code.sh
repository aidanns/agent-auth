#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Per-package vulture sweep for unused functions, classes, methods,
# imports, variables, and attributes at ``--min-confidence 80``.
# Soft (advisory) gate: this script always exits 0 regardless of how
# many findings vulture surfaces, so the CI job that calls it never
# blocks merge. See ADR 0047 for the soft-gate decision and issue
# #578 for the triage that locked in confidence threshold, per-package
# shape, and annotation-driven (``# noqa: F841``) suppression.
#
# False positives are suppressed at their call site with
# ``# noqa: F841`` rather than via ``[tool.vulture]`` in each
# pyproject.toml so the suppression is reviewable in context.
#
# Output shape: one ``=== <pkg> ===`` banner per package followed by
# vulture's findings (or ``no findings`` when clean). Captured into
# ``$GITHUB_STEP_SUMMARY`` by ``.github/workflows/check-lint.yml`` so
# reviewers see findings on the PR's Checks tab without the job
# having to fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

MIN_CONFIDENCE=80

total_findings=0
for pkg_dir in packages/*/; do
  pkg_name="$(basename "${pkg_dir}")"
  src_dir="${pkg_dir}src"
  # Skip packages that ship no ``src/`` tree (e.g. the deprecated
  # gpg-backend-cli-host directory whose body was deleted in #316
  # but whose stale egg-info lingers).
  [[ -d "${src_dir}" ]] || continue
  if [[ -z "$(find "${src_dir}" -name '*.py' -print -quit 2>/dev/null)" ]]; then
    continue
  fi

  echo "=== ${pkg_name} ==="

  # Vulture exits 3 when it finds dead code, 0 when clean. Capture
  # the output and translate the exit code so a finding does NOT
  # propagate through ``set -e``.
  if findings="$(uv run --no-sync vulture --min-confidence "${MIN_CONFIDENCE}" "${src_dir}" 2>&1)"; then
    echo "no findings"
  else
    rc=$?
    if [[ ${rc} -eq 3 ]]; then
      # Exit 3 is the documented "found dead code" signal. Print
      # the findings and continue; the gate is advisory.
      echo "${findings}"
      finding_count=$(printf '%s\n' "${findings}" | grep -cE '^[^=]' || true)
      total_findings=$((total_findings + finding_count))
    else
      # Any other non-zero exit is a vulture invocation failure
      # (bad arguments, missing path, etc.) — print and re-raise
      # so the maintainer notices the misconfiguration. Soft-gate
      # only covers vulture's "dead code found" case, not its own
      # bugs.
      echo "vulture failed with exit code ${rc}:" >&2
      echo "${findings}" >&2
      exit "${rc}"
    fi
  fi
done

echo
echo "Total dead-code findings (advisory, --min-confidence ${MIN_CONFIDENCE}): ${total_findings}"
