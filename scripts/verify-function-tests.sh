#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify that every leaf function in the functional decomposition is
# allocated to at least one test under the workspace test trees.
# Tests live under packages/<svc>/tests/ post-#270 plus the
# workspace-only tests/ at the root (release / openapi-spec / scan-
# failure checks). Pass the repo root and let the verify tool walk
# down into every tests/ tree it finds.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

systems-engineering function verify \
  "${REPO_ROOT}/design/functional_decomposition.yaml" \
  --test-directory "${REPO_ROOT}"
