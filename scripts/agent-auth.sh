#!/usr/bin/env bash

# Run the agent-auth CLI inside the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

VENV_DIR=".venv-$(uname -s)-$(uname -m)"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install -e ".[dev]"
fi

exec "${VENV_DIR}/bin/agent-auth" "$@"
