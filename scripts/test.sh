#!/usr/bin/env bash

# Run the agent-auth test suite inside the project virtualenv.
#
# Modes (mutually exclusive):
#   --unit                     (default) only the in-process unit tests
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
    --unit | --all)
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

case "${mode}" in
  unit)
    exec uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    ;;
  integration)
    integration_path="tests/integration/"
    if [[ -n "${service}" ]]; then
      integration_path="${SERVICE_PATHS[${service}]}"
    fi
    exec uv run --no-sync pytest "${integration_path}" "$@"
    ;;
  all)
    uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    exec uv run --no-sync pytest tests/integration/ "$@"
    ;;
esac
