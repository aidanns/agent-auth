#!/usr/bin/env bash

# Run all configured linters. Currently a no-op placeholder: individual linters
# (ruff, shellcheck, taplo, mdformat) are tracked as separate tooling-and-ci
# items and will be wired in here as each lands.

set -euo pipefail

echo "task lint: no linters configured yet; see .claude/instructions/tooling-and-ci.md"
