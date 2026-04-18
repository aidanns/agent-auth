#!/usr/bin/env bash

# Build sdist and wheel distributions into dist/ using the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

VENV_DIR=".venv-$(uname -s)-$(uname -m)"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install -e ".[dev]"
fi

"${VENV_DIR}/bin/python" -m build --outdir "${REPO_ROOT}/dist"
