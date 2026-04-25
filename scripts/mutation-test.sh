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

# Source the shared bootstrap so PYTHONPATH includes the per-package
# tests/ trees that ship the gpg-bridge / things-bridge subprocess
# fakes. mutmut copies the workspace into ./mutants/ and reruns
# pytest there, but the test fakes are launched via
# ``python -m gpg_backend_fake`` / ``python -m things_client_fake``
# in fresh subprocesses that don't inherit pytest's in-process
# ``[tool.pytest.ini_options].pythonpath``. Without PYTHONPATH the
# subprocesses fail to resolve the fake modules and every gpg-bridge
# server test is reported by mutmut as ``no_tests``.
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

cd "${REPO_ROOT}"

# Re-anchor PYTHONPATH at the mutants/ workspace too so
# ``python -m gpg_backend_fake`` resolves there once mutmut has copied
# the per-package tests/ trees into mutants/packages/<svc>/tests/. The
# bootstrap exports the absolute repo-root paths, which mutmut's
# subprocess inheritance keeps; appending the mutants/ paths in front
# guarantees the fake modules resolve to the mutated copy when the
# tests run from inside mutants/.
PYTHONPATH="${REPO_ROOT}/mutants/packages/things-bridge/tests:${REPO_ROOT}/mutants/packages/gpg-bridge/tests${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

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
