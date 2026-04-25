#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Force a refresh of the YAML-driven release PR.
#
# The default release flow opens / updates a release PR automatically
# on every push to `main` via `.github/workflows/release-pr.yml`. This
# script is the manual escape hatch: it dispatches that same workflow
# on demand (e.g. when a maintainer wants to refresh the PR after
# editing a `changelog/@unreleased/*.yml` directly via the GitHub UI,
# or when CI is unhappy and the workflow needs a clean retry).
#
# It does NOT cut a tag on its own — tagging happens inside
# `release-tag.yml` when the release PR merges, so the release flow
# always goes through the standard PR review gate. See
# CONTRIBUTING.md § "Release process" and ADR 0041.
#
# Usage:
#   scripts/release.sh           # dispatch release-pr.yml against main
#   scripts/release.sh --help    # this help

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: scripts/release.sh
  Dispatches `.github/workflows/release-pr.yml` against `main`. The
  workflow opens or updates the release PR. Merge that PR through the
  normal review gate to cut a release.

  See CONTRIBUTING.md § "Release process" for the full flow.
EOF
}

while [[ $# -gt 0 ]]; do
  case "${1}" in
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "release: unexpected argument '${1}'" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "release: 'gh' (GitHub CLI) is required but not found on PATH." >&2
  exit 1
fi

echo "release: dispatching release-pr.yml on main ..."
gh workflow run release-pr.yml --ref main

echo "release: dispatched. Watch progress at:"
echo "  https://github.com/aidanns/agent-auth/actions/workflows/release-pr.yml"
