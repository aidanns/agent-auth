#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify that the external CLI tools required to run this project's
# Taskfile targets are available on PATH and meet the minimum versions
# pinned in .github/tool-versions.yaml. Intended as a pre-flight check
# — run it locally before `task test`, `task verify-standards`, etc.
#
# Version policy: the manifest pin is a MINIMUM within the same major.
# Local dev environments (brew, apt, asdf) frequently ship ahead of the
# CI-pinned version; blocking on e.g. `yq 4.52` when CI is on `4.44` is
# friction without benefit. CI itself installs the exact manifest
# version via .github/actions/setup-toolchain, so its runs remain
# reproducible. Tools with a different major than the manifest (or
# older within the same major) fail this check.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST="${REPO_ROOT}/.github/tool-versions.yaml"

if [[ ! -f "${MANIFEST}" ]]; then
  echo "verify-dependencies: ${MANIFEST} is missing." >&2
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "verify-dependencies: 'yq' is required to parse ${MANIFEST}." >&2
  echo "Install it from https://github.com/mikefarah/yq and re-run." >&2
  exit 1
fi

# Tools required on PATH but whose versions are not pinned in the
# manifest (e.g. host tools supplied by the OS or devcontainer, or
# tools pinned by ref/SHA rather than a semver).
PRESENCE_TOOLS=(
  # keep-sorted start
  python3
  systems-engineering
  yq
  # keep-sorted end
)

# Tools whose versions ARE pinned in the manifest. Each row is
# pipe-separated:
#   <path-name>|<manifest-key>|<version-command>|<version-regex>
# The regex captures the version into \1 from the first matching line
# of the command's combined stdout+stderr.
VERSIONED_TOOLS=(
  # keep-sorted start
  "keep-sorted|keep-sorted|keep-sorted --version|^v?([0-9]+\\.[0-9]+\\.[0-9]+)"
  "mdformat|mdformat|mdformat --version|mdformat ([0-9]+\\.[0-9]+\\.[0-9]+)"
  "ripsecrets|ripsecrets|ripsecrets --version|ripsecrets ([0-9]+\\.[0-9]+\\.[0-9]+)"
  "ruff|ruff|ruff --version|ruff ([0-9]+\\.[0-9]+\\.[0-9]+)"
  "shellcheck|shellcheck|shellcheck --version|version: ([0-9]+\\.[0-9]+\\.[0-9]+)"
  "shfmt|shfmt|shfmt --version|v([0-9]+\\.[0-9]+\\.[0-9]+)"
  "taplo|taplo|taplo --version|taplo ([0-9]+\\.[0-9]+\\.[0-9]+)"
  "task|go-task|task --version|v?([0-9]+\\.[0-9]+\\.[0-9]+)"
  "treefmt|treefmt|treefmt --version|v?([0-9]+\\.[0-9]+\\.[0-9]+)"
  "uv|uv|uv --version|uv ([0-9]+\\.[0-9]+\\.[0-9]+)"
  # keep-sorted end
)

missing=()
too_old=()
major_drift=()
unparseable=()

for tool in "${PRESENCE_TOOLS[@]}"; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    missing+=("${tool}")
  fi
done

# ``sort -V`` places the lexicographically-smaller version first. If the
# manifest pin sorts first (or both strings are equal), the installed
# version is >= the pin.
version_is_at_least() {
  local installed="$1" pinned="$2"
  [[ "$(printf '%s\n%s\n' "${installed}" "${pinned}" | sort -V | head -1)" == "${pinned}" ]]
}

for entry in "${VERSIONED_TOOLS[@]}"; do
  IFS='|' read -r tool key version_cmd regex <<<"${entry}"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    missing+=("${tool}")
    continue
  fi

  pinned="$(yq -r ".[\"${key}\"].version" "${MANIFEST}")"
  if [[ -z "${pinned}" || "${pinned}" == "null" ]]; then
    echo "verify-dependencies: ${MANIFEST} is missing '${key}.version'." >&2
    exit 1
  fi

  raw="$(eval "${version_cmd}" 2>&1 || true)"
  installed=""
  while IFS= read -r line; do
    if [[ "${line}" =~ ${regex} ]]; then
      installed="${BASH_REMATCH[1]}"
      break
    fi
  done <<<"${raw}"

  if [[ -z "${installed}" ]]; then
    unparseable+=("${tool}: could not parse version from '${version_cmd}' output")
    continue
  fi

  if [[ "${installed%%.*}" != "${pinned%%.*}" ]]; then
    major_drift+=("${tool}: installed ${installed}, manifest pins ${pinned} (different major)")
    continue
  fi

  if ! version_is_at_least "${installed}" "${pinned}"; then
    too_old+=("${tool}: installed ${installed}, manifest pins ${pinned} (need >= within same major)")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "verify-dependencies: required tools are missing from PATH:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
fi

if [[ ${#too_old[@]} -gt 0 ]]; then
  echo "verify-dependencies: required tools are older than the manifest pin:" >&2
  printf '  - %s\n' "${too_old[@]}" >&2
fi

if [[ ${#major_drift[@]} -gt 0 ]]; then
  echo "verify-dependencies: required tools run a different major than the manifest pin:" >&2
  printf '  - %s\n' "${major_drift[@]}" >&2
fi

if [[ ${#unparseable[@]} -gt 0 ]]; then
  echo "verify-dependencies: could not determine installed version for some tools:" >&2
  printf '  - %s\n' "${unparseable[@]}" >&2
fi

if [[ ${#missing[@]} -gt 0 || ${#too_old[@]} -gt 0 || ${#major_drift[@]} -gt 0 || ${#unparseable[@]} -gt 0 ]]; then
  echo "Install or upgrade the tools above and re-run." >&2
  exit 1
fi

echo "verify-dependencies: all required tools are on PATH at versions compatible with ${MANIFEST}."
