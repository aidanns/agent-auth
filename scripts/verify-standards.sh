#!/usr/bin/env bash

# Verify that project-level standards required by .claude/instructions/
# are in place. Currently asserts that Dependabot is configured for both
# the pip and github-actions ecosystems (see tooling-and-ci.md Security).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "error: ${DEPENDABOT_CONFIG} is missing" >&2
  exit 1
fi

for ecosystem in pip github-actions; do
  if ! grep -Eq "^[[:space:]]*-[[:space:]]+package-ecosystem:[[:space:]]*\"?${ecosystem}\"?[[:space:]]*$" "${DEPENDABOT_CONFIG}"; then
    echo "error: ${DEPENDABOT_CONFIG} does not declare the '${ecosystem}' ecosystem" >&2
    exit 1
  fi
done
