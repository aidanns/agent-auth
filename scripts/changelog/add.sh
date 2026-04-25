#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the changelog-add CLI inside the project virtualenv.
#
# Wraps `python scripts/changelog/add.py` so callers can run
# `task changelog:add -- --type fix --description "..." --pr 123`
# (or the alias `task changelog-add -- ...`) without having to know
# about the per-OS/arch venv that `_bootstrap_venv.sh` sets up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=../_bootstrap_venv.sh
source "${REPO_ROOT}/scripts/_bootstrap_venv.sh"

exec uv run --no-sync python "${REPO_ROOT}/scripts/changelog/add.py" "$@"
