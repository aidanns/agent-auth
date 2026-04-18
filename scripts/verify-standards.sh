#!/usr/bin/env bash

# Verify generic project standards mandated by .claude/instructions/.
# Checks grow over time as new cross-cutting standards are added. Today:
#
#   1. Taskfile.yml exposes every task named in REQUIRED_TASKS (see
#      tooling-and-ci.md Orchestration).
#
# Project-specific checks (e.g. dependency coverage) live in their own
# sibling scripts — see verify-dependencies.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v task >/dev/null 2>&1; then
  echo "verify-standards: 'task' (go-task) is not on PATH." >&2
  echo "Install it from https://taskfile.dev/installation/ and re-run." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "verify-standards: 'python3' is required to parse the task catalogue." >&2
  exit 1
fi

# keep-sorted start
REQUIRED_TASKS=(
  build
  format
  install-hooks
  lint
  release
  test
  verify-dependencies
  verify-design
  verify-function-tests
  verify-standards
)
# keep-sorted end

catalogue="$(task --list-all --json)"

# Capture into a variable (not process substitution) so `set -e` catches a
# crash in the python helper — otherwise a parser failure silently yields an
# empty `missing` array and the check falsely reports success.
missing_output="$(python3 - "${catalogue}" "${REQUIRED_TASKS[@]}" <<'PY'
import json
import sys

catalogue = json.loads(sys.argv[1])
required = set(sys.argv[2:])
present = {task["name"] for task in catalogue.get("tasks", [])}
for name in sorted(required - present):
    print(name)
PY
)"

if [[ -n "${missing_output}" ]]; then
  mapfile -t missing <<<"${missing_output}"
  echo "verify-standards: Taskfile.yml is missing required tasks:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

echo "verify-standards: Taskfile.yml exposes all required tasks."
