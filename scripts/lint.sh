#!/usr/bin/env bash

# Run shellcheck over every tracked *.sh file and ruff check over every
# tracked *.py file. ruff is provided by the per-OS/arch project venv
# (installed as a `dev` extra).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v shellcheck >/dev/null 2>&1; then
  echo "task lint: 'shellcheck' is not on PATH." >&2
  echo "Install via 'apt-get install shellcheck' (Linux) or" >&2
  echo "'brew install shellcheck' (macOS), then re-run." >&2
  exit 1
fi

# Capture into a variable (not process substitution) so `set -e` catches a
# git failure — mapfile always succeeds regardless of the inner command's
# exit status, which would otherwise silently pass the gate with zero
# files outside a valid checkout.
shell_files_raw="$(git ls-files '*.sh')"

if [[ -z "${shell_files_raw}" ]]; then
  echo "task lint: no *.sh files tracked; skipping shellcheck."
else
  mapfile -t shell_files <<<"${shell_files_raw}"
  shellcheck "${shell_files[@]}"
fi

python_files_raw="$(git ls-files '*.py')"

if [[ -z "${python_files_raw}" ]]; then
  echo "task lint: no *.py files tracked; skipping ruff check."
  exit 0
fi

mapfile -t python_files <<<"${python_files_raw}"

# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

"${VENV_DIR}/bin/ruff" check "${python_files[@]}"
