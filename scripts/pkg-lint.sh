#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Lint a single workspace package's *.py and *.sh files via ruff-check
# and shellcheck-exec. Invoked from per-package Taskfiles via
# ``task <svc>:lint``. The authoritative sweep lives in
# scripts/lint.sh (which also runs keep-sorted over every tracked
# file); this helper narrows ruff and shellcheck to the package
# directory so a service can be iterated on without waiting for the
# full sweep.
#
# Shell comment pitfall: placing ``shellcheck`` at the start of a
# comment line triggers SC1073 because shellcheck itself scans for
# ``# shellcheck <directive>`` markers. The wrapping above is
# intentional — do not put ``shellcheck`` flush at the line start.
#
# keep-sorted deliberately stays workspace-only: its annotated blocks
# cross-cut the tree (e.g. CHANGELOG, lockfiles, workflow matrices)
# and partitioning them by package would produce misleading results.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/pkg-lint.sh <svc>" >&2
  exit 2
fi

svc="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

pkg_dir="packages/${svc}"
if [[ ! -d "${pkg_dir}" ]]; then
  echo "pkg-lint: unknown workspace package '${svc}' (no ${pkg_dir}/)" >&2
  exit 2
fi

require_tool() {
  local tool="$1"
  local install_hint="$2"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "pkg-lint: '${tool}' is not on PATH." >&2
    echo "${install_hint}" >&2
    exit 1
  fi
}

require_tool shellcheck \
  "Install via 'apt-get install shellcheck' (Linux) or 'brew install shellcheck' (macOS), then re-run."
require_tool ruff \
  "Install via 'uv tool install ruff' or from https://github.com/astral-sh/ruff/releases, then re-run."

# Same pattern as scripts/lint.sh: capture into a variable so `set -e`
# catches a git failure (mapfile always succeeds and would otherwise
# silently pass the gate outside a valid checkout).
shell_files_raw="$(git ls-files "${pkg_dir}/*.sh")"
python_files_raw="$(git ls-files "${pkg_dir}/*.py")"

if [[ -n "${shell_files_raw}" ]]; then
  mapfile -t shell_files <<<"${shell_files_raw}"
  shellcheck "${shell_files[@]}"
else
  echo "pkg-lint: no *.sh files tracked under ${pkg_dir}; skipping shellcheck."
fi

if [[ -n "${python_files_raw}" ]]; then
  mapfile -t python_files <<<"${python_files_raw}"
  ruff check "${python_files[@]}"
else
  echo "pkg-lint: no *.py files tracked under ${pkg_dir}; skipping ruff check."
fi
