#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the agent-auth test suite inside the project virtualenv.
#
# Modes (mutually exclusive):
#   --unit         (default) only the in-process unit tests
#   --integration  only the Docker-backed integration tests
#   --all          both layers, unit first
#
# Extra arguments after the mode flag are passed straight through to
# pytest. In --all mode the same args are forwarded to both layers.

set -euo pipefail

mode="unit"
if [[ $# -gt 0 ]]; then
  case "$1" in
    --unit | --integration | --all)
      mode="${1#--}"
      shift
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
    exec uv run --no-sync pytest tests/integration/ "$@"
    ;;
  all)
    uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    exec uv run --no-sync pytest tests/integration/ "$@"
    ;;
esac
