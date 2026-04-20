#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify that the external CLI tools required to run this project's
# Taskfile targets are available on PATH. Intended as a pre-flight check
# — run it locally before `task test`, `task verify-standards`, etc. to
# get an actionable list of anything missing.

set -euo pipefail

REQUIRED_TOOLS=(
  # keep-sorted start
  keep-sorted
  mdformat
  python3
  ruff
  shellcheck
  shfmt
  systems-engineering
  taplo
  task
  uv
  yq
  # keep-sorted end
)

missing=()
for tool in "${REQUIRED_TOOLS[@]}"; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    missing+=("${tool}")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "verify-dependencies: required tools are missing from PATH:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  echo "Install them and re-run." >&2
  exit 1
fi

echo "verify-dependencies: all required tools are on PATH (${REQUIRED_TOOLS[*]})."
