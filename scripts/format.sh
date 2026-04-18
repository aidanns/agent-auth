#!/usr/bin/env bash

# Run shfmt over every tracked *.sh file. Pass --check to diff-only mode
# (CI uses this); default rewrites files in place. shfmt reads formatting
# options from .editorconfig at the repo root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

mode="write"
for arg in "$@"; do
  case "${arg}" in
    --check) mode="check" ;;
    *)
      echo "task format: unknown argument '${arg}'" >&2
      echo "usage: scripts/format.sh [--check]" >&2
      exit 2
      ;;
  esac
done

if ! command -v shfmt >/dev/null 2>&1; then
  echo "task format: 'shfmt' is not on PATH." >&2
  echo "Install from https://github.com/mvdan/sh/releases or" >&2
  echo "'brew install shfmt' (macOS), then re-run." >&2
  exit 1
fi

# Capture into a variable (not process substitution) so `set -e` catches a
# git failure — mapfile always succeeds regardless of the inner command's
# exit status, which would otherwise silently pass the gate with zero
# files outside a valid checkout.
shell_files_raw="$(git ls-files '*.sh')"

if [[ -z "${shell_files_raw}" ]]; then
  echo "task format: no *.sh files tracked; nothing to format."
  exit 0
fi

mapfile -t shell_files <<<"${shell_files_raw}"

if [[ "${mode}" == "check" ]]; then
  shfmt -d "${shell_files[@]}"
else
  shfmt -w "${shell_files[@]}"
fi
