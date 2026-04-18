#!/usr/bin/env bash

# Run the things-bridge CLI inside the project virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"
export UV_PROJECT_ENVIRONMENT

uv sync --extra dev --quiet

exec uv run --no-sync things-bridge "$@"
