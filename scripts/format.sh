#!/usr/bin/env bash

# Run every configured formatter over its tracked files: shfmt for
# *.sh, mdformat for *.md, taplo for *.toml. shfmt reads formatting
# options from .editorconfig; mdformat reads .mdformat.toml; taplo
# reads taplo.toml.
#
# Pass --check to diff-only mode (CI uses this); default rewrites files
# in place.

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

require_tool() {
  local tool="$1"
  local install_hint="$2"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "task format: '${tool}' is not on PATH." >&2
    echo "${install_hint}" >&2
    exit 1
  fi
}

# Capture each tracked-file listing into a variable (not process
# substitution) so `set -e` catches a git failure — mapfile always
# succeeds regardless of the inner command's exit status, which would
# otherwise silently pass the gate with zero files outside a valid
# checkout.
list_tracked() {
  local pattern="$1"
  git ls-files "${pattern}"
}

require_tool shfmt \
  "Install from https://github.com/mvdan/sh/releases or 'brew install shfmt' (macOS), then re-run."
require_tool mdformat \
  "Install via 'pip install mdformat mdformat-gfm mdformat-tables' in the project venv, then re-run."
require_tool taplo \
  "Install from https://github.com/tamasfe/taplo/releases or 'brew install taplo' (macOS), then re-run."

shell_files_raw="$(list_tracked '*.sh')"
markdown_files_raw="$(list_tracked '*.md')"
toml_files_raw="$(list_tracked '*.toml')"

format_group() {
  local label="$1"
  local files_raw="$2"
  shift 2
  if [[ -z "${files_raw}" ]]; then
    echo "task format: no ${label} files tracked; skipping."
    return 0
  fi
  local files
  mapfile -t files <<<"${files_raw}"
  "$@" "${files[@]}"
}

if [[ "${mode}" == "check" ]]; then
  format_group "*.sh" "${shell_files_raw}" shfmt -d
  format_group "*.md" "${markdown_files_raw}" mdformat --check
  format_group "*.toml" "${toml_files_raw}" taplo format --check
else
  format_group "*.sh" "${shell_files_raw}" shfmt -w
  format_group "*.md" "${markdown_files_raw}" mdformat
  format_group "*.toml" "${toml_files_raw}" taplo format
fi
