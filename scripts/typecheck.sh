#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the Python type checkers (mypy + pyright) against every
# packages/<svc>/src/ tree and tests/. Both ship as dev dependencies
# and are invoked through uv so the project venv is used.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

uv run --no-sync mypy
exec uv run --no-sync pyright
