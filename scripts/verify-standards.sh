#!/usr/bin/env bash

# Verify generic project standards mandated by .claude/instructions/.
# Checks grow over time as new cross-cutting standards are added. Today:
#
#   1. Taskfile.yml exposes every task named in REQUIRED_TASKS (see
#      tooling-and-ci.md Orchestration).
#   2. .github/dependabot.yml covers every dependency ecosystem actually
#      in use by this repository with minor/patch grouping (see
#      tooling-and-ci.md Security). An ecosystem is "in use" when its
#      manifest files are present; ecosystems without manifests are
#      skipped rather than required.

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

if ! command -v yq >/dev/null 2>&1; then
  echo "verify-standards: 'yq' (https://github.com/mikefarah/yq) is required to parse the dependabot config." >&2
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

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "verify-standards: ${DEPENDABOT_CONFIG} is missing" >&2
  exit 1
fi

required_ecosystems=()

if [[ -f pyproject.toml ]] || [[ -f setup.py ]] || compgen -G 'requirements*.txt' >/dev/null; then
  required_ecosystems+=(pip)
fi

if compgen -G '.github/workflows/*.yml' >/dev/null || compgen -G '.github/workflows/*.yaml' >/dev/null; then
  required_ecosystems+=(github-actions)
fi

if [[ ${#required_ecosystems[@]} -eq 0 ]]; then
  echo "verify-standards: no known dependency ecosystems detected; skipping dependabot coverage check."
else
  for ecosystem in "${required_ecosystems[@]}"; do
    matched=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .[\"package-ecosystem\"]" "${DEPENDABOT_CONFIG}")
    if [[ "${matched}" != "${ecosystem}" ]]; then
      echo "verify-standards: dependabot.yml does not declare the '${ecosystem}' ecosystem" >&2
      exit 1
    fi

    update_types=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .groups.[].update-types[]" "${DEPENDABOT_CONFIG}")
    for update_type in minor patch; do
      if ! printf '%s\n' "${update_types}" | grep -qFx "${update_type}"; then
        echo "verify-standards: ecosystem '${ecosystem}' does not group '${update_type}' updates" >&2
        exit 1
      fi
    done
  done

  echo "verify-standards: dependabot.yml covers detected ecosystems (${required_ecosystems[*]}) with minor/patch grouping."
fi
