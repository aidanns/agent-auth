#!/usr/bin/env bash

# Verify that the external CLI tools required to run this project's
# Taskfile targets are available on PATH. Intended as a pre-flight check
# — run it locally before `task test`, `task verify-standards`, etc. to
# get an actionable list of anything missing.

set -euo pipefail

# keep-sorted start
REQUIRED_TOOLS=(
  python3
  task
  yq
)
# keep-sorted end

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
