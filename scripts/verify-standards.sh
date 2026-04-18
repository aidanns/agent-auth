#!/usr/bin/env bash

# Verify project-level standards mandated by .claude/instructions/ are in
# place:
#
#   1. Taskfile.yml exposes every task named in REQUIRED_TASKS (see
#      tooling-and-ci.md Orchestration).
#   2. .github/dependabot.yml declares the pip and github-actions
#      ecosystems and groups minor/patch updates for each (see
#      tooling-and-ci.md Security).

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

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "verify-standards: ${DEPENDABOT_CONFIG} is missing" >&2
  exit 1
fi

for ecosystem in pip github-actions; do
  block=$(awk -v eco="${ecosystem}" '
    /^[[:space:]]*-[[:space:]]+package-ecosystem:/ {
      if (capture) exit
      if ($0 ~ "\"?" eco "\"?[[:space:]]*$") capture = 1
    }
    capture { print }
  ' "${DEPENDABOT_CONFIG}")

  if [[ -z "${block}" ]]; then
    echo "verify-standards: dependabot.yml does not declare the '${ecosystem}' ecosystem" >&2
    exit 1
  fi

  for required in "groups:" '"minor"' '"patch"'; do
    if ! printf '%s\n' "${block}" | grep -qF "${required}"; then
      echo "verify-standards: ecosystem '${ecosystem}' is missing '${required}' in its grouping config" >&2
      exit 1
    fi
  done
done

echo "verify-standards: dependabot.yml declares pip and github-actions with minor/patch grouping."
