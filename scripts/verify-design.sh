#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify that all leaf functions in the functional decomposition are allocated
# within the product breakdown.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

systems-engineering product verify \
  -p "${REPO_ROOT}/design/product_breakdown.yaml" \
  -f "${REPO_ROOT}/design/functional_decomposition.yaml"
