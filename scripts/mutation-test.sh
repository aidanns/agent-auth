#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the mutmut mutation-testing pass against the security-critical
# modules configured in pyproject.toml's [tool.mutmut] section, then
# export the CI/CD stats JSON that scripts/check-mutation-score.sh
# reads to gate against the fail_under floor.
#
# Positional args are forwarded to `mutmut run` (e.g. --max-children
# to cap parallelism on constrained runners).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# mutmut writes mutant copies under ./mutants/; clear it so stale
# results from a previous run don't skew the score.
rm -rf mutants

# --max-children defaults to the CPU count. The run ignores exit code:
# mutmut exits non-zero whenever any mutant survives, but we want the
# score check (not the raw survivor count) to gate CI.
uv run mutmut run "$@" || true

uv run mutmut export-cicd-stats

echo "---"
uv run mutmut results || true
