#!/usr/bin/env bash

# Ensure the per-OS/arch project virtualenv exists and reflects the
# current pyproject.toml. Designed to be sourced (not executed) so the
# caller can then exec the installed entry point in the same process.
# The helper chdirs to the repo root; subsequent relative paths in the
# caller (e.g. `tests/` for pytest, implicit pyproject.toml lookup for
# `python -m build`) resolve there.
#
# Exports:
#   REPO_ROOT — absolute path to the repo root.
#   VENV_DIR — path to the virtualenv, relative to the repo root.

set -euo pipefail

BOOTSTRAP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${BOOTSTRAP_SCRIPT_DIR}/.." && pwd)"
export REPO_ROOT

cd "${REPO_ROOT}"

VENV_DIR=".venv-$(uname -s)-$(uname -m)"
export VENV_DIR

PYPROJECT_HASH_MARKER="${VENV_DIR}/pyproject.sha256"

# `shasum -a 256` is present on both macOS (perl-backed, part of the base
# system) and Linux (usually via coreutils or perl), unlike GNU `sha256sum`
# which is not installed on macOS by default.
read -r current_hash _ < <(shasum -a 256 pyproject.toml)

needs_install=0
if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
  # `--clear` covers a half-built venv from an interrupted prior run
  # (dir exists but bin/pip missing); on a clean miss it's a no-op.
  echo "Bootstrapping venv at ${VENV_DIR}..." >&2
  python3 -m venv --clear "${VENV_DIR}"
  needs_install=1
elif [[ ! -f "${PYPROJECT_HASH_MARKER}" ]] || {
  read -r stored_hash <"${PYPROJECT_HASH_MARKER}"
  [[ "${stored_hash}" != "${current_hash}" ]]
}; then
  echo "Refreshing venv (pyproject.toml changed)..." >&2
  needs_install=1
fi

if [[ "${needs_install}" -eq 1 ]]; then
  "${VENV_DIR}/bin/pip" install --quiet -e ".[dev]"
  printf '%s\n' "${current_hash}" >"${PYPROJECT_HASH_MARKER}"
fi
