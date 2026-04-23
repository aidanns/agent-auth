#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Regenerate the rendered variants of design/*.yaml in place.
#
# The yaml files are the source of truth (verified by
# `scripts/verify-design.sh`); the sibling .{md,csv,d2,png,svg}
# variants are generated view renders that ship with the repo for
# human browsing (GitHub renders the .md and .svg inline).
#
# The generator is `systems-engineering`
# (https://github.com/aidanns/systems-engineering); CI installs it via
# .github/actions/setup-toolchain. The output files inherit SPDX
# metadata from REUSE.toml overrides (the generator does not emit
# inline SPDX headers and post-processing them in would couple the
# generator to the licensing policy).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v systems-engineering >/dev/null 2>&1; then
  echo "design-generate: 'systems-engineering' CLI is not on PATH." >&2
  echo "  Install via the project's setup-toolchain action or" >&2
  echo "  'bash <(curl -fsSL https://raw.githubusercontent.com/aidanns/systems-engineering/main/install.sh)'." >&2
  exit 1
fi

systems-engineering function diagram \
  "${REPO_ROOT}/design/functional_decomposition.yaml" \
  -o "${REPO_ROOT}/design"

systems-engineering product diagram \
  "${REPO_ROOT}/design/product_breakdown.yaml" \
  -o "${REPO_ROOT}/design"

# Post-process the rendered Markdown through mdformat so the generated
# output matches the project-wide Markdown format policy. Without this,
# `task format -- --check` fails on a freshly generated file (table
# alignment differs between the generator's writer and mdformat).
# mdformat is idempotent, so running it again produces no further diff.
if command -v mdformat >/dev/null 2>&1; then
  mdformat \
    "${REPO_ROOT}/design/functional_decomposition.md" \
    "${REPO_ROOT}/design/product_breakdown.md"
else
  echo "design-generate: 'mdformat' is not on PATH; skipping Markdown post-format." >&2
  echo "  Install via 'uv tool install mdformat --with mdformat-gfm --with mdformat-tables'." >&2
fi
