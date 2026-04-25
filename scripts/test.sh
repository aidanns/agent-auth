#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the workspace test suite inside the project virtualenv.
#
# Modes (mutually exclusive):
#   --unit                     (default) only the in-process unit tests
#   --fast                     curated smoke subset for pre-commit (runs in <1s)
#   --integration [<service>]  Docker-backed integration tests; optional
#                              service name runs only that slice. Valid
#                              services: agent-auth, gpg-bridge,
#                              things-bridge, things-cli,
#                              things-client-applescript.
#   --all                      both layers, unit first (always full
#                              integration suite)
#
# Extra arguments after the mode (and optional service) are passed
# straight through to pytest. In --all mode the same args are
# forwarded to both layers.

set -euo pipefail

# Per-package integration test directories. Each package owns its
# slice of the Docker-backed suite under packages/<svc>/tests/
# integration/ (relocated from the monolithic tests/integration/
# tree in #270).
declare -A SERVICE_PATHS=(
  ["agent-auth"]=packages/agent-auth/tests/integration/
  ["gpg-bridge"]=packages/gpg-bridge/tests/integration/
  ["things-bridge"]=packages/things-bridge/tests/integration/
  ["things-cli"]=packages/things-cli/tests/integration/
  ["things-client-applescript"]=packages/things-client-cli-applescript/tests/integration/
)

# Workspace-wide unit-test paths. Each package owns a tests/ tree
# (post-#270); the root tests/ tree only carries cross-service
# checks (release/openapi/scan-failure). Listing them explicitly
# rather than passing a single root keeps integration trees out of
# the unit-mode invocation without an --ignore for every per-package
# integration/ subdir.
UNIT_TEST_PATHS=(
  # keep-sorted start
  packages/agent-auth-common/tests/
  packages/agent-auth/tests/
  packages/gpg-backend-cli-host/tests/
  packages/gpg-bridge/tests/
  packages/gpg-cli/tests/
  packages/things-bridge/tests/
  packages/things-cli/tests/
  packages/things-client-cli-applescript/tests/
  tests/
  # keep-sorted end
)

# Pytest's discovery ignores the per-package integration/ subdirs
# in unit mode so a `--unit` run never tries to start Docker.
UNIT_IGNORE_OPTS=(
  --ignore=packages/agent-auth/tests/integration
  --ignore=packages/gpg-bridge/tests/integration
  --ignore=packages/things-bridge/tests/integration
  --ignore=packages/things-cli/tests/integration
  --ignore=packages/things-client-cli-applescript/tests/integration
)

mode="unit"
service=""
if [[ $# -gt 0 ]]; then
  case "$1" in
    --unit | --fast | --all)
      mode="${1#--}"
      shift
      ;;
    --integration)
      mode="integration"
      shift
      if [[ $# -gt 0 && "$1" != -* ]]; then
        service="$1"
        shift
        if [[ -z "${SERVICE_PATHS[${service}]+x}" ]]; then
          echo "error: unknown service '${service}'" >&2
          echo "       valid services: ${!SERVICE_PATHS[*]}" >&2
          exit 2
        fi
      fi
      ;;
    *) : ;;
  esac
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

# Curated smoke subset for --fast mode: the security-critical core
# (tokens, scopes, crypto, keys). Picked for speed (sub-second) and
# coverage of code whose silent breakage would block downstream tests.
FAST_TESTS=(
  # keep-sorted start
  packages/agent-auth/tests/test_crypto.py
  packages/agent-auth/tests/test_keys.py
  packages/agent-auth/tests/test_scopes.py
  packages/agent-auth/tests/test_tokens.py
  # keep-sorted end
)

# Integration tests are slow enough that knowing where the time goes
# matters in CI. ``--durations=0 --durations-min=0.1`` reports every
# setup/call/teardown phase >100ms (so per-test container start/stop
# costs are visible), and ``log_cli`` streams the
# ``integration.timing`` phase logs (compose start/stop, image build,
# health-wait) live instead of burying them in pytest's per-test
# capture.
INTEGRATION_TIMING_OPTS=(
  --durations=0
  --durations-min=0.1
  -o log_cli=true
  -o log_cli_level=INFO
  -o "log_cli_format=%(asctime)s %(levelname)s %(name)s %(message)s"
)

case "${mode}" in
  unit)
    uv run --no-sync pytest "${UNIT_IGNORE_OPTS[@]}" "${UNIT_TEST_PATHS[@]}" "$@"
    # The workspace pytest run leaves behind a unified ``.coverage``
    # database; per-package floors are enforced by querying it
    # afterwards (#273). Skip the gate when extra args are present —
    # an iterative ``-k <test>`` invocation would deliberately under-
    # exercise its package's surface.
    if [[ $# -eq 0 ]]; then
      exec scripts/check-package-coverage.sh
    fi
    ;;
  fast)
    # Disable coverage collection: --fast runs a curated smoke subset
    # that only exercises ~6% of packages/*/src/, so the per-package
    # floors enforced by ``check-package-coverage.sh`` would always
    # fail. The floor is measured against --unit (the authoritative
    # gate).
    exec uv run --no-sync pytest --no-cov "${FAST_TESTS[@]}" "$@"
    ;;
  integration)
    # Same rationale as --fast: integration tests exercise a different
    # surface than packages/*/src/ (Docker lifecycle, cross-service
    # contracts), so the unit-based floor doesn't apply. Integration
    # coverage is tracked separately; see plans/pytest-cov-threshold.md
    # "Out of scope".
    if [[ -n "${service}" ]]; then
      integration_paths=("${SERVICE_PATHS[${service}]}")
    else
      integration_paths=("${SERVICE_PATHS[@]}")
    fi
    exec uv run --no-sync pytest --no-cov "${INTEGRATION_TIMING_OPTS[@]}" "${integration_paths[@]}" "$@"
    ;;
  all)
    uv run --no-sync pytest "${UNIT_IGNORE_OPTS[@]}" "${UNIT_TEST_PATHS[@]}" "$@"
    # Same skip-on-extra-args carve-out as the ``unit`` mode.
    if [[ $# -eq 0 ]]; then
      scripts/check-package-coverage.sh
    fi
    exec uv run --no-sync pytest --no-cov "${INTEGRATION_TIMING_OPTS[@]}" "${SERVICE_PATHS[@]}" "$@"
    ;;
esac
