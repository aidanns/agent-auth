#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Single source of truth for the release-build commands.
#
# Both `.github/workflows/release-publish.yml` (on tag push) and
# `.github/workflows/release-dryrun.yml` (on every PR + push to main)
# invoke this script. Centralising the build commands here means the
# PR-time dry-run always exercises exactly what the publish path will
# run; a divergence between the two would defeat the point of the
# dry-run gate. See issue #325 and ADR 0016.
#
# This script ONLY builds; signing, SBOM generation, cosign bundles,
# SLSA provenance, and asset uploads stay in `release-publish.yml` so
# the dry-run never touches those side-effecting steps.
#
# Usage:
#   scripts/build-release-artifacts.sh            # build into ./dist/
#   scripts/build-release-artifacts.sh --out DIR  # build into DIR/
#
# Environment:
#   UV_PROJECT_ENVIRONMENT — optional; honoured by uv as usual.

set -euo pipefail

OUT_DIR="dist"

while [[ $# -gt 0 ]]; do
  case "${1}" in
    --out)
      OUT_DIR="${2:?--out requires a directory}"
      shift 2
      ;;
    --out=*)
      OUT_DIR="${1#--out=}"
      shift
      ;;
    -h | --help)
      sed -n '/^# Usage:/,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "build-release-artifacts: unexpected argument '${1}'" >&2
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "build-release-artifacts: 'uv' is required but not found on PATH." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

# Today this is `uv build` at the workspace root, which matches what
# `release-publish.yml` ran before this script was extracted. The
# workspace-split regression that motivated #325 means this currently
# fails on `main` (setuptools rejects the workspace-root pyproject) —
# that failure is the intended PR-time signal. Issue #324 rewrites
# this step to a per-package `uv build --package <name>` loop; once it
# lands the dry-run will go green and the gate can move from
# informational (`continue-on-error: true` on the dry-run job) to
# required-status-check.
uv build --out-dir "${OUT_DIR}"
