#!/usr/bin/env bash

# Install git hooks via lefthook. Lefthook configuration is not yet committed
# (tracked as a separate tooling-and-ci item). This script is a placeholder
# so the task surface stays stable; it will run `lefthook install` once a
# `lefthook.yml` lands at the repo root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${REPO_ROOT}/lefthook.yml" ]]; then
  if ! command -v lefthook >/dev/null 2>&1; then
    echo "task install-hooks: lefthook.yml present but 'lefthook' is not on PATH." >&2
    echo "Install lefthook (https://lefthook.dev) then re-run." >&2
    exit 1
  fi
  exec lefthook install
fi

echo "task install-hooks: no lefthook.yml yet; see .claude/instructions/tooling-and-ci.md"
