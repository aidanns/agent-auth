#!/usr/bin/env bash

# Run the agent-auth test suite inside the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

"${VENV_DIR}/bin/python" -m pytest tests/ "$@"
