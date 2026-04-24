#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify the design directory:
#
#   1. Every leaf function in functional_decomposition.yaml is allocated
#      within product_breakdown.yaml (systems-engineering product verify).
#   2. The rendered variants (.md, .csv, .d2, .png, .svg) match what
#      scripts/design-generate.sh produces from the yaml — catches the
#      "yaml updated, sibling artefacts forgotten" class of drift flagged
#      in issue #141.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

systems-engineering product verify \
  -p "${REPO_ROOT}/design/product_breakdown.yaml" \
  -f "${REPO_ROOT}/design/functional_decomposition.yaml"

# Regenerate the rendered variants into the worktree and assert the
# checked-in files match. `git diff --exit-code` exits 1 on any diff,
# which bubbles up through `set -e`. Writing into the worktree (rather
# than into a temp dir + diff per file) keeps the error output
# actionable — the developer sees `design/functional_decomposition.md`
# in the diff and runs `task design:generate` to fix it.
#
# PNGs are excluded from the gate because the d2 rasteriser output is
# not byte-stable across architectures and minor toolchain versions
# (font metrics differ between the developer's macOS/aarch64 machine
# and the Ubuntu x86_64 CI runner). PNGs are convenience previews for
# a GitHub reader; the authoritative deterministic renders are the
# `.d2` source and the `.svg` vector output, both gated below.
cd "${REPO_ROOT}"
"${SCRIPT_DIR}/design-generate.sh" >/dev/null
if ! git diff --exit-code -- design/ ':(exclude)design/*.png'; then
  echo "verify-design: design/ artefacts are out of date with functional_decomposition.yaml / product_breakdown.yaml." >&2
  echo "  Run 'task design:generate' and commit the result. See issue #141." >&2
  exit 1
fi

echo "verify-design: functional decomposition allocation checks pass and rendered design/ artefacts match the yaml (PNG excluded — see script comment)."
