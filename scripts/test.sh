#!/usr/bin/env bash

# Run the agent-auth test suite inside the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

VENV_DIR=".venv-$(uname -s)-$(uname -m)"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

# Re-run the editable install unconditionally so that a venv created before
# a new `[dev]` dependency was added picks it up on the next `task test`.
"${VENV_DIR}/bin/pip" install --quiet -e ".[dev]"

"${VENV_DIR}/bin/python" -m pytest tests/ "$@"
