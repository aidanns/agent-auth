#!/usr/bin/env bash

# Run every configured linter: shellcheck over every tracked *.sh file,
# and keep-sorted (lint mode) over every tracked file to verify that
# annotated sorted blocks have not drifted.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

require_tool() {
  local tool="$1"
  local install_hint="$2"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "task lint: '${tool}' is not on PATH." >&2
    echo "${install_hint}" >&2
    exit 1
  fi
}

require_tool shellcheck \
  "Install via 'apt-get install shellcheck' (Linux) or 'brew install shellcheck' (macOS), then re-run."
require_tool keep-sorted \
  "Install from https://github.com/google/keep-sorted/releases or 'go install github.com/google/keep-sorted@latest', then re-run."

# Capture into a variable (not process substitution) so `set -e` catches a
# git failure — mapfile always succeeds regardless of the inner command's
# exit status, which would otherwise silently pass the gate with zero
# files outside a valid checkout.
shell_files_raw="$(git ls-files '*.sh')"
tracked_files_raw="$(git ls-files)"

if [[ -n "${shell_files_raw}" ]]; then
  mapfile -t shell_files <<<"${shell_files_raw}"
  shellcheck "${shell_files[@]}"
else
  echo "task lint: no *.sh files tracked; skipping shellcheck."
fi

if [[ -n "${tracked_files_raw}" ]]; then
  mapfile -t tracked_files <<<"${tracked_files_raw}"
  keep-sorted --mode=lint "${tracked_files[@]}"
else
  echo "task lint: no tracked files; skipping keep-sorted."
fi
