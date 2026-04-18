#!/usr/bin/env bash

# Run all configured formatters. Currently a no-op placeholder: individual
# formatters (ruff format, shfmt, taplo, mdformat, treefmt) are tracked as
# separate tooling-and-ci items and will be wired in here as each lands.

set -euo pipefail

echo "task format: no formatters configured yet; see .claude/instructions/tooling-and-ci.md"
