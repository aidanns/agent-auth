#!/usr/bin/env bash

# Verify that project-level standards required by .claude/instructions/
# are in place. Currently asserts that Dependabot is configured for the
# pip and github-actions ecosystems and that each groups minor/patch
# updates (see tooling-and-ci.md Security).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "error: ${DEPENDABOT_CONFIG} is missing" >&2
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
    echo "error: ${DEPENDABOT_CONFIG} does not declare the '${ecosystem}' ecosystem" >&2
    exit 1
  fi

  for required in "groups:" '"minor"' '"patch"'; do
    if ! printf '%s\n' "${block}" | grep -qF "${required}"; then
      echo "error: ecosystem '${ecosystem}' is missing '${required}' in its grouping config" >&2
      exit 1
    fi
  done
done
