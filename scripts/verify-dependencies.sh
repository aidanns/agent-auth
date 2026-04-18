#!/usr/bin/env bash

# Verify that .github/dependabot.yml covers every dependency ecosystem
# actually in use by this repository, with minor/patch updates grouped
# per ecosystem. An ecosystem is treated as "in use" when its manifest
# files are present in the tree; ecosystems with no manifests are
# skipped rather than required (e.g. a pure-Python repo should not be
# forced to declare a `npm` block).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v yq >/dev/null 2>&1; then
  echo "verify-dependencies: 'yq' (https://github.com/mikefarah/yq) is required to parse the dependabot config." >&2
  exit 1
fi

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "verify-dependencies: ${DEPENDABOT_CONFIG} is missing" >&2
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
  echo "verify-dependencies: no known dependency ecosystems detected; nothing to verify."
  exit 0
fi

for ecosystem in "${required_ecosystems[@]}"; do
  matched=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .[\"package-ecosystem\"]" "${DEPENDABOT_CONFIG}")
  if [[ "${matched}" != "${ecosystem}" ]]; then
    echo "verify-dependencies: dependabot.yml does not declare the '${ecosystem}' ecosystem" >&2
    exit 1
  fi

  update_types=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .groups.[].update-types[]" "${DEPENDABOT_CONFIG}")
  for update_type in minor patch; do
    if ! printf '%s\n' "${update_types}" | grep -qFx "${update_type}"; then
      echo "verify-dependencies: ecosystem '${ecosystem}' does not group '${update_type}' updates" >&2
      exit 1
    fi
  done
done

echo "verify-dependencies: dependabot.yml covers detected ecosystems (${required_ecosystems[*]}) with minor/patch grouping."
