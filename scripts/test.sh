#!/usr/bin/env bash

# Run the agent-auth test suite inside the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]"
fi

.venv/bin/python -m pytest tests/ "$@"
