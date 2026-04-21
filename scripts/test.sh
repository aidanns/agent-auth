#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the agent-auth test suite inside the project virtualenv.
#
# Modes (mutually exclusive):
#   --unit                     (default) only the in-process unit tests
#   --fast                     curated smoke subset for pre-commit (runs in <1s)
#   --integration [<service>]  Docker-backed integration tests; optional
#                              service name runs only that slice. Valid
#                              services: agent-auth, things-bridge,
#                              things-cli, things-client-applescript.
#   --all                      both layers, unit first (always full
#                              integration suite)
#
# Extra arguments after the mode (and optional service) are passed
# straight through to pytest. In --all mode the same args are
# forwarded to both layers.

set -euo pipefail

declare -A SERVICE_PATHS=(
  ["agent-auth"]=tests/integration/agent_auth/
  ["things-bridge"]=tests/integration/things_bridge/
  ["things-cli"]=tests/integration/things_cli/
  ["things-client-applescript"]=tests/integration/things_client_applescript/
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
  tests/test_crypto.py
  tests/test_keys.py
  tests/test_scopes.py
  tests/test_tokens.py
  # keep-sorted end
)

case "${mode}" in
  unit)
    exec uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    ;;
  fast)
    # Disable coverage collection: --fast runs a curated smoke subset
    # that only exercises ~6% of src/, so the --cov-fail-under=74 floor
    # configured in pyproject.toml would always fail. The floor is
    # measured against --unit (the authoritative gate).
    exec uv run --no-sync pytest --no-cov "${FAST_TESTS[@]}" "$@"
    ;;
  integration)
    # Same rationale as --fast: integration tests exercise a different
    # surface than src/ (Docker lifecycle, cross-service contracts),
    # so the unit-based floor doesn't apply. Integration coverage is
    # tracked separately; see plans/pytest-cov-threshold.md "Out of
    # scope".
    integration_path="tests/integration/"
    if [[ -n "${service}" ]]; then
      integration_path="${SERVICE_PATHS[${service}]}"
    fi
    exec uv run --no-sync pytest --no-cov "${integration_path}" "$@"
    ;;
  all)
    uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    exec uv run --no-sync pytest --no-cov tests/integration/ "$@"
    ;;
esac
