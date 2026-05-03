#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Per-package dependency-license allowlist gate (issue #575).
#
# For each workspace member under ``packages/<svc>/`` (or the single
# package supplied as $1), enumerate the resolved dependency closure
# (runtime via ``uv export --package <svc>`` ∪ workspace dev via
# ``uv export --extra dev``) and dispatch to the Python helper at
# ``scripts/ci/check_license_allowlist.py``. The helper reads the
# allowlist, parses pip-licenses metadata for the venv, and applies
# the multi-license disjunction + per-package exception logic. See
# ``design/decisions/0048-dependency-license-allowlist-gate.md``.
#
# Exit codes:
#   0 — every package passed.
#   1 — one or more packages flagged a violation. The script lists
#       every offending package before exiting (mirrors the
#       ``check-package-coverage.sh`` shape — no early bail).
#   2 — invocation / setup error.
#
# Usage:
#   scripts/check-license-allowlist.sh                  # all workspace members
#   scripts/check-license-allowlist.sh agent-auth       # one specific member

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

# Compute one package's closure as a sorted ``name==version`` list:
# the package's runtime deps from ``uv export --package <pkg>``
# unioned with the workspace dev deps from
# ``uv export --extra dev`` at the root. ``uv export`` writes
# requirements.txt format with ``# via …`` comments and env-marker
# clauses; the Python helper parses those out.
emit_closure_to() {
  local pkg="$1"
  local out_file="$2"
  {
    uv export \
      --package "${pkg}" \
      --no-emit-workspace \
      --no-hashes \
      --format requirements-txt
    uv export \
      --no-emit-workspace \
      --no-hashes \
      --extra dev \
      --format requirements-txt
  } | sort -u >"${out_file}"
}

# Walk the active venv's installed dists and emit a JSON dump of
# the license metadata. Reads ``License-Expression`` (PEP 639),
# ``License`` (legacy free-form), and the ``License ::`` classifier
# list per dist. Captured once per invocation rather than once per
# package — the dump is whole-venv state, identical for every
# package in the matrix. The Python helper handles the SPDX
# disjunction / conjunction logic.
emit_metadata_to() {
  local out_file="$1"
  uv run --no-sync python \
    "${SCRIPT_DIR}/ci/check_license_allowlist.py" \
    --emit-metadata >"${out_file}"
}

# Run the Python gate against one package. Returns 0 on pass, 1 on
# fail. Captures the metadata dump once per invocation rather than
# per-package — the dump is whole-venv state, identical for every
# package in the matrix.
check_one() {
  local pkg="$1"
  local metadata_file="$2"

  local closure_file
  closure_file=$(mktemp)
  emit_closure_to "${pkg}" "${closure_file}"

  local exceptions_arg=()
  local exceptions_file="packages/${pkg}/licenses.exceptions.yml"
  if [[ -f "${exceptions_file}" ]]; then
    exceptions_arg=(--exceptions "${exceptions_file}")
  fi

  local rc=0
  uv run --no-sync python \
    "${SCRIPT_DIR}/ci/check_license_allowlist.py" \
    --package "${pkg}" \
    --closure "${closure_file}" \
    --metadata "${metadata_file}" \
    "${exceptions_arg[@]}" || rc=$?

  rm -f "${closure_file}"
  return "${rc}"
}

main() {
  local metadata_file
  metadata_file=$(mktemp)
  emit_metadata_to "${metadata_file}"

  local fail=0
  if [[ $# -ge 1 ]]; then
    # Single-package invocation — the per-package CI matrix uses this
    # path so each job's output is scoped to its own package.
    if ! check_one "$1" "${metadata_file}"; then
      fail=1
    fi
  else
    for pkg_dir in packages/*/; do
      local pkg
      pkg="$(basename "${pkg_dir}")"
      if ! check_one "${pkg}" "${metadata_file}"; then
        fail=1
      fi
    done
  fi

  rm -f "${metadata_file}"

  if [[ "${fail}" -ne 0 ]]; then
    exit 1
  fi
}

main "$@"
