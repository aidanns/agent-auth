#!/usr/bin/env bash

# Verify that every leaf function in the functional decomposition is allocated
# to at least one test in the tests/ directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

systems-engineering function verify \
  "${REPO_ROOT}/design/functional_decomposition.yaml" \
  --test-directory "${REPO_ROOT}/tests/"
