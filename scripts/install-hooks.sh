#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Install git hooks via lefthook. Reads lefthook.yml from the repo root
# and registers the pre-commit shim under .git/hooks/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${REPO_ROOT}/lefthook.yml" ]]; then
  echo "task install-hooks: ${REPO_ROOT}/lefthook.yml is missing." >&2
  echo "  Restore lefthook.yml or remove the install-hooks task." >&2
  exit 1
fi

if ! command -v lefthook >/dev/null 2>&1; then
  echo "task install-hooks: 'lefthook' is not on PATH." >&2
  echo "Install lefthook (https://lefthook.dev) then re-run." >&2
  exit 1
fi

cd "${REPO_ROOT}"
exec lefthook install
