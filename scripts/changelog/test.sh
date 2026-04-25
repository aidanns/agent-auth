#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the unit tests for the workspace-level changelog tooling under
# scripts/changelog/. Kept self-contained (separate from `task test`)
# so the workspace coverage gate stays scoped to packages/*/src/ —
# scripts/changelog/ is tooling code, not shipped service code.
#
# Usage:
#   scripts/changelog/test.sh          # default: scripts/changelog/tests
#   scripts/changelog/test.sh -- -k x  # extra args forwarded to pytest

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=../_bootstrap_venv.sh
source "${REPO_ROOT}/scripts/_bootstrap_venv.sh"

# `--no-cov` keeps these tests off the workspace `.coverage` database
# so `scripts/check-package-coverage.sh`'s per-package floors don't
# pick them up (they aren't under packages/*/src/, but skipping the
# instrumentation is the safer guard against future drift).
exec uv run --no-sync pytest --no-cov scripts/changelog/tests "$@"
