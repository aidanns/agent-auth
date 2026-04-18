#!/usr/bin/env bash

# Ensure the per-OS/arch project virtualenv exists and reflects the
# current pyproject.toml / uv.lock. Designed to be sourced (not
# executed) so the caller can then exec the installed entry point in
# the same process. The helper chdirs to the repo root; subsequent
# relative paths in the caller (e.g. `tests/` for pytest, implicit
# pyproject.toml lookup for `python -m build`) resolve there.
#
# Exports:
#   REPO_ROOT — absolute path to the repo root.
#   UV_PROJECT_ENVIRONMENT — path to the virtualenv, relative to the
#     repo root (per-OS/arch so Darwin and Linux venvs can coexist on
#     a shared filesystem).

set -euo pipefail

BOOTSTRAP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${BOOTSTRAP_SCRIPT_DIR}/.." && pwd)"
export REPO_ROOT

cd "${REPO_ROOT}"

UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"
export UV_PROJECT_ENVIRONMENT

# `uv sync` creates the venv on first run and refreshes it when
# pyproject.toml or uv.lock change — no manual hash marker needed.
uv sync --extra dev --quiet
