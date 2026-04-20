#!/usr/bin/env bash

# Run the agent-auth test suite inside the project virtualenv.
#
# Modes (mutually exclusive):
#   --unit         (default) only the in-process unit tests
#   --fast         curated smoke subset for pre-commit (runs in <1s)
#   --integration  only the Docker-backed integration tests
#   --all          both layers, unit first
#
# Extra arguments after the mode flag are passed straight through to
# pytest. In --all mode the same args are forwarded to both layers.

set -euo pipefail

mode="unit"
if [[ $# -gt 0 ]]; then
  case "$1" in
    --unit | --fast | --integration | --all)
      mode="${1#--}"
      shift
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
    exec uv run --no-sync pytest "${FAST_TESTS[@]}" "$@"
    ;;
  integration)
    exec uv run --no-sync pytest tests/integration/ "$@"
    ;;
  all)
    uv run --no-sync pytest tests/ --ignore=tests/integration "$@"
    exec uv run --no-sync pytest tests/integration/ "$@"
    ;;
esac
