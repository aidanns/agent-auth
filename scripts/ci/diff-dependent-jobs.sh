#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Print the list of GitHub check-run names whose outcome depends only on
# the code at the PR's head SHA — the "diff-dependent" set, distinct from
# checks that read PR metadata (labels, title, body, milestone).
#
# Used by the `plan` job in `.github/workflows/ci.yml` (issue #527 /
# Option 4 — verified partial re-run on label-only events). On a
# `labeled` / `unlabeled` event the head SHA is the same as the prior
# `synchronize`, so any check-run that already produced `success` on
# that SHA is still authoritative; those checks can skip and the
# aggregator's `skipped = failure` rule (#441) is relaxed for them
# specifically. The list of "those checks" must be derived rather
# than copy-pasted, otherwise drift between ci.yml and the probe
# silently breaks the safety invariant — see "Keeping the list in
# sync" in #527 for the rationale.
#
# Derivation: read ci.yml's `required-checks-passed.needs:` array,
# subtract the planning job (`plan`) and the metadata-dependent
# allowlist, and expand each surviving ci.yml job ID into the leaf
# check-run names GitHub publishes for that workflow_call child.
#
# The job-ID → leaf-check-runs mapping is hard-coded inline in this
# script. Each entry is small enough to read at a glance, and the
# accompanying `tests/test_ci_diff_dependent_jobs_sh.py` test runs
# the script against the real ci.yml and asserts every emitted name
# matches a check-run GitHub actually produces, so drift between this
# script and either ci.yml's needs list or any child workflow's
# matrix membership fails CI rather than degrading silently.
#
# Usage:
#   scripts/ci/diff-dependent-jobs.sh [path-to-ci.yml]
#
# Default ci.yml path is `.github/workflows/ci.yml` relative to the
# repo root (auto-detected via the script's own location).
#
# Output: one check-run name per line on stdout. No external
# dependencies beyond `yq` (already in the repo's required tooling
# per CLAUDE.md and `scripts/verify-dependencies.sh`).

set -euo pipefail

if [[ $# -gt 1 ]]; then
  echo "diff-dependent-jobs: expected at most 1 arg (path to ci.yml); got $#" >&2
  exit 2
fi

# Repo root resolved from the script's own location so callers can
# invoke from any cwd (the `plan` job runs from the workspace root,
# but tests may invoke from elsewhere).
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../.." && pwd)
ci_yml="${1:-${repo_root}/.github/workflows/ci.yml}"

if [[ ! -f "${ci_yml}" ]]; then
  echo "diff-dependent-jobs: ci.yml not found at: ${ci_yml}" >&2
  exit 2
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "diff-dependent-jobs: yq is required but not installed" >&2
  exit 2
fi

# Metadata-dependent ci.yml job IDs. Their outcome may change
# between label events on the same head SHA, so they MUST re-run
# unconditionally. Default for any new child is "diff-dependent" —
# only add a job here if its evaluation reads PR metadata
# (labels, title, body, milestone, etc.).
#
# - check-changelog: reads `pull_request.labels` for the bypass and
#   `pull_request.head.ref` for the entry-name slug check.
# - check-pull-request: reads commit-message metadata via
#   `pull_request.{base,head}.sha` and DCO sign-off, both of which
#   are diff-dependent in practice — but the workflow ALSO houses
#   pr-lint validators (title, body, commit-message block per ADR
#   0037) once they migrate, which read PR metadata. Listed here
#   so the gating story stays uniform across pr-lint additions.
metadata_dependent=(
  check-changelog
  check-pull-request
)

# Read `required-checks-passed.needs:` as a flat list, one job ID per
# line. `yq -r '.[] | .'` flattens the YAML array; the input is the
# `needs` block.
needs=$(yq -r '.jobs."required-checks-passed".needs[]' "${ci_yml}")

# Apply the subtractions (`plan` + metadata-dependent set) using
# associative-array set membership so the script remains O(n).
declare -A excluded=([plan]=1)
for j in "${metadata_dependent[@]}"; do
  excluded["${j}"]=1
done

# Iterate the surviving job IDs in the order ci.yml lists them. Order
# is stable so the script's stdout is deterministic, which the tests
# rely on for golden-file comparisons.
diff_dependent_job_ids=()
while IFS= read -r jid; do
  [[ -z "${jid}" ]] && continue
  if [[ -z "${excluded["${jid}"]+x}" ]]; then
    diff_dependent_job_ids+=("${jid}")
  fi
done <<<"${needs}"

# Expand each ci.yml job ID into the leaf check-run names GitHub
# publishes. The naming convention is `<calling-job-display-name> /
# <called-job-display-name>` — when a workflow_call child has its
# own internal `Required checks passed` aggregator (check-fmt,
# check-lint, check-security) we probe that single rollup; otherwise
# we list the matrix-expanded leaves explicitly.
#
# Display names (the parent's `name:` in ci.yml, when present) are
# spelled exactly as GitHub renders them in the PR check rollup —
# capitalisation matters. See the issue body for a sample rollup.
emit_leaves() {
  local jid="$1"
  case "${jid}" in
    check-fmt)
      echo "Check Fmt / Required checks passed"
      ;;
    check-security)
      echo "Check Security / Required checks passed"
      ;;
    check-lint)
      echo "check-lint / Required checks passed"
      ;;
    check-docs)
      echo "check-docs / check-docs"
      ;;
    check-publish)
      echo "check-publish / check-publish"
      ;;
    check-release)
      echo "check-release / check-release"
      ;;
    check-standards)
      echo "check-standards / verify-standards"
      ;;
    build)
      echo "build / build"
      ;;
    test-unit)
      # Matrix: one row per workspace member; names per the parens
      # variant convention (#414). Keep in sync with
      # `.github/workflows/test-unit.yml`'s `matrix.package`.
      echo "test-unit / unit-tests (agent-auth)"
      echo "test-unit / unit-tests (agent-auth-common)"
      echo "test-unit / unit-tests (gpg-bridge)"
      echo "test-unit / unit-tests (gpg-cli)"
      echo "test-unit / unit-tests (things-bridge)"
      echo "test-unit / unit-tests (things-cli)"
      echo "test-unit / unit-tests (things-client-cli-applescript)"
      ;;
    test-integration)
      # Matrix: per-package Docker-backed integration shards. Keep in
      # sync with `.github/workflows/test-integration.yml`.
      echo "test-integration / integration-tests (agent-auth)"
      echo "test-integration / integration-tests (gpg-bridge)"
      echo "test-integration / integration-tests (things-bridge)"
      echo "test-integration / integration-tests (things-cli)"
      echo "test-integration / integration-tests (things-client-applescript)"
      ;;
    test-smoke)
      # Matrix: install-from-wheels for the externally-shipped CLIs.
      # Keep in sync with `.github/workflows/test-smoke.yml`'s
      # `matrix.service`.
      echo "test-smoke / install-from-wheels (gpg-bridge, gpg-bridge)"
      echo "test-smoke / install-from-wheels (things-cli, things-cli)"
      ;;
    test-system)
      echo "test-system / macos-applescript"
      ;;
    *)
      echo "diff-dependent-jobs: unmapped ci.yml job ID: ${jid}" >&2
      echo "  add a case arm to emit_leaves() (or, if the job is" >&2
      echo "  metadata-dependent, add it to the metadata_dependent" >&2
      echo "  array near the top of this script)" >&2
      exit 2
      ;;
  esac
}

for jid in "${diff_dependent_job_ids[@]}"; do
  emit_leaves "${jid}"
done
