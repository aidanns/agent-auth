#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run `reuse lint` to verify every tracked file carries SPDX licensing
# metadata either inline (via an SPDX header) or through REUSE.toml.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

exec uv run --no-sync reuse lint
