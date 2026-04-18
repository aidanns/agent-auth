#!/usr/bin/env bash

# Run shellcheck over every tracked *.sh file.

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
  echo "task lint: no *.sh files tracked; nothing to lint."
  exit 0
fi

mapfile -t shell_files <<<"${shell_files_raw}"

shellcheck "${shell_files[@]}"
