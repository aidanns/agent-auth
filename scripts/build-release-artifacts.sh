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

# ``--all-packages`` enumerates every workspace member in
# ``[tool.uv.workspace].members`` and builds one wheel + one sdist per
# member into ``${OUT_DIR}``. The repo-root pyproject.toml is a
# workspace shell with no build target — running ``uv build`` against
# it would have setuptools reject the multiple-top-level-packages
# flat layout (the workspace-split regression that motivated #325).
# Issue #324 took the build off ``uv build`` at the workspace root
# and onto this per-package loop.
uv build --all-packages --out-dir "${OUT_DIR}"
