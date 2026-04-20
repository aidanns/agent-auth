#!/usr/bin/env bash

# Run the Python type checkers (mypy + pyright) against src/ and tests/.
# Both ship as dev dependencies and are invoked through uv so the
# project venv is used.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

uv run --no-sync mypy
exec uv run --no-sync pyright
