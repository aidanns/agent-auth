#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Format a single workspace package's tracked files (*.sh, *.py, *.md,
# *.toml) using the same toolchain as scripts/format.sh (shfmt, ruff
# format, mdformat, taplo). Invoked from per-package Taskfiles via
# `task <svc>:format`. Pass `-- --check` to run in diff-only mode.
#
# scripts/format.sh still owns the workspace-wide sweep (it also
# covers repo-root files like CHANGELOG.md and uv.lock-adjacent
# configuration). This helper is the per-service iteration path.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/pkg-format.sh <svc> [--check]" >&2
  exit 2
fi

svc="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

pkg_dir="packages/${svc}"
if [[ ! -d "${pkg_dir}" ]]; then
  echo "pkg-format: unknown workspace package '${svc}' (no ${pkg_dir}/)" >&2
  exit 2
fi

mode="write"
for arg in "$@"; do
  case "${arg}" in
    --check) mode="check" ;;
    *)
      echo "pkg-format: unknown argument '${arg}'" >&2
      echo "usage: scripts/pkg-format.sh <svc> [--check]" >&2
      exit 2
      ;;
  esac
done

require_tool() {
  local tool="$1"
  local install_hint="$2"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "pkg-format: '${tool}' is not on PATH." >&2
    echo "${install_hint}" >&2
    exit 1
  fi
}

require_tool shfmt \
  "Install from https://github.com/mvdan/sh/releases or 'brew install shfmt' (macOS), then re-run."
require_tool ruff \
  "Install via 'uv tool install ruff' or from https://github.com/astral-sh/ruff/releases, then re-run."
require_tool mdformat \
  "Install via 'uv tool install mdformat --with mdformat-gfm --with mdformat-tables', then re-run."
require_tool taplo \
  "Install from https://github.com/tamasfe/taplo/releases or 'brew install taplo' (macOS), then re-run."

list_tracked() {
  local pattern="$1"
  git ls-files "${pattern}"
}

shell_files_raw="$(list_tracked "${pkg_dir}/*.sh")"
python_files_raw="$(list_tracked "${pkg_dir}/*.py")"
markdown_files_raw="$(list_tracked "${pkg_dir}/*.md")"
toml_files_raw="$(list_tracked "${pkg_dir}/*.toml")"

format_group() {
  local label="$1"
  local files_raw="$2"
  shift 2
  if [[ -z "${files_raw}" ]]; then
    echo "pkg-format: no ${label} files tracked under ${pkg_dir}; skipping."
    return 0
  fi
  local files
  mapfile -t files <<<"${files_raw}"
  "$@" "${files[@]}"
}

if [[ "${mode}" == "check" ]]; then
  format_group "*.sh" "${shell_files_raw}" shfmt -d
  format_group "*.py" "${python_files_raw}" ruff format --check
  format_group "*.md" "${markdown_files_raw}" mdformat --check
  format_group "*.toml" "${toml_files_raw}" taplo format --check
else
  format_group "*.sh" "${shell_files_raw}" shfmt -w
  format_group "*.py" "${python_files_raw}" ruff format
  format_group "*.md" "${markdown_files_raw}" mdformat
  format_group "*.toml" "${toml_files_raw}" taplo format
fi
