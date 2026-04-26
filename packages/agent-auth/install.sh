#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Install or upgrade ``agent-auth`` (the token server, token CLI,
# and the out-of-process approval notifier) from a published
# GitHub release into a stdlib-managed Python virtualenv. Optionally
# uninstall with ``--uninstall``. Optionally point at a directory of
# locally-built wheels with ``--local <dir>`` (used by the
# release-publish CI integration test).
#
# Running this script installs only the ``agent-auth`` package and
# its workspace dependency ``agent-auth-common``; use the per-service
# installers under ``packages/<service>/install.sh`` for the bridges
# or other clients.

set -euo pipefail

GITHUB_REPO="aidanns/agent-auth"
TOOL_NAME="agent-auth"
PACKAGE_SUBDIR="packages/agent-auth"
INSTALL_DIR="${HOME}/.local/share/${TOOL_NAME}"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"

# Wheel filename prefix this service publishes under. Wheel filenames
# follow PEP 625 normalisation: hyphens in the dist name become
# underscores in the filename.
SERVICE_WHEEL_PREFIX="agent_auth-"

# Console scripts shipped by this service (matches
# ``[project.scripts]`` in the package's ``pyproject.toml``). Each
# entry is symlinked from ``<venv>/bin/<entry>`` into
# ``~/.local/bin/<entry>``.
ENTRYPOINTS=(
  agent-auth
  agent-auth-notifier
)

# Workspace packages this service depends on at runtime, hard-coded
# from ``packages/agent-auth/pyproject.toml`` ``[project] dependencies``
# filtered to workspace members. The full set is audited against the
# ADR 0036 workspace-dep-graph allowlist via
# ``scripts/verify_workspace_deps.py``; if you add a workspace dep
# here, add it to the allowlist in lockstep.
#
# Each entry is a wheel-filename prefix after PEP 625 normalisation
# (hyphens become underscores).
WORKSPACE_DEP_WHEEL_PREFIXES=(
  agent_auth_common-
)

# --- Argument parsing ---

LOCAL_DIR=""
VERSION=""
UNINSTALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      UNINSTALL=true
      shift
      ;;
    --local)
      if [[ $# -lt 2 ]]; then
        echo "install.sh: --local requires a directory argument." >&2
        exit 1
      fi
      LOCAL_DIR="$2"
      shift 2
      ;;
    -h | --help)
      cat <<EOF
Usage: install.sh [VERSION] [--local DIR] [--uninstall]

  VERSION       Release tag to install (e.g. v0.13.0). Defaults to the latest release.
  --local DIR   Install from a directory of locally-built wheels + .sha256 files
                (used by CI integration tests; mutually exclusive with VERSION).
  --uninstall   Remove ${TOOL_NAME} from ${INSTALL_DIR} and ${BIN_DIR}.
  -h, --help    Show this help text.
EOF
      exit 0
      ;;
    *)
      VERSION="$1"
      shift
      ;;
  esac
done

# --- Uninstall ---

if ${UNINSTALL}; then
  echo "Uninstalling ${TOOL_NAME}..."
  for entry in "${ENTRYPOINTS[@]}"; do
    link="${BIN_DIR}/${entry}"
    if [[ -L "${link}" || -e "${link}" ]]; then
      rm -f "${link}"
      echo "Removed: ${link}"
    fi
  done
  if [[ -d "${VENV_DIR}" ]]; then
    rm -rf "${VENV_DIR}"
    echo "Removed: ${VENV_DIR}"
  fi
  rmdir "${INSTALL_DIR}" 2>/dev/null || true
  echo "Done."
  exit 0
fi

# --- Prerequisite checks ---

PYTHON=""
for candidate in python3 python; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    if "${candidate}" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
      PYTHON="${candidate}"
      break
    fi
  fi
done

if [[ -z "${PYTHON}" ]]; then
  cat >&2 <<'EOF'
install.sh: Python 3.11+ is required but not found on PATH.

Install Python 3.11+ for your platform:
  macOS (Homebrew):  brew install python@3.12
  Ubuntu/Debian:     sudo apt install python3 python3-venv
  RHEL/Fedora:       sudo dnf install python3
EOF
  exit 1
fi

if ! "${PYTHON}" -c "import venv" 2>/dev/null; then
  cat >&2 <<'EOF'
install.sh: the Python venv module is required but not importable.

Install it for your platform:
  Ubuntu/Debian:  sudo apt install python3-venv
  RHEL/Fedora:    venv ships with python3 by default
EOF
  exit 1
fi

if [[ -z "${LOCAL_DIR}" ]] && ! command -v curl >/dev/null 2>&1; then
  echo "install.sh: 'curl' is required to download release assets." >&2
  exit 1
fi

# --- Helper functions ---

# Pick the right sha256 verifier for this platform. macOS ships
# ``shasum -a 256 -c`` instead of ``sha256sum``.
sha256_check() {
  local checksum_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "${checksum_file}"
  else
    shasum -a 256 -c "${checksum_file}"
  fi
}

# GitHub-API curl with optional auth token (``GITHUB_TOKEN`` set in
# CI) to dodge the unauthenticated rate limit.
gh_curl_json() {
  local url="$1"
  local out="$2"
  local auth=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth+=(-H "Authorization: token ${GITHUB_TOKEN}")
  fi
  curl -fsSL "${auth[@]}" -H "Accept: application/vnd.github+json" -o "${out}" "${url}"
}

gh_download_asset() {
  local url="$1" out="$2"
  local auth=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth+=(-H "Authorization: token ${GITHUB_TOKEN}")
  fi
  curl -fsSL "${auth[@]}" -H "Accept: application/octet-stream" -o "${out}" "${url}"
}

# Acquire one wheel + its .sha256 from --local DIR or from the release
# JSON cached at ${RELEASE_JSON}. Caller passes a wheel-filename
# prefix (e.g. ``${SERVICE_WHEEL_PREFIX}`` or ``agent_auth_common-``)
# that picks exactly one matching wheel asset.
acquire_wheel() {
  local prefix="$1"
  if [[ -n "${LOCAL_DIR}" ]]; then
    # Glob expands to the literal pattern when nothing matches under
    # default options, so test the first hit for existence rather than
    # piping through ls (SC2012). The expectation is exactly one
    # wheel per prefix per --local dir.
    local matches=("${LOCAL_DIR}/${prefix}"*.whl)
    local wheel="${matches[0]}"
    if [[ ! -f "${wheel}" ]]; then
      echo "install.sh: no wheel matching ${prefix}*.whl in ${LOCAL_DIR}" >&2
      exit 1
    fi
    local checksum="${wheel}.sha256"
    if [[ ! -f "${checksum}" ]]; then
      echo "install.sh: missing checksum file ${checksum}" >&2
      exit 1
    fi
    cp "${wheel}" "${checksum}" "${WORK_DIR}/"
    return
  fi

  # Remote mode: pick the matching wheel + .sha256 out of the
  # release-asset list.
  local lines
  lines=$(
    PREFIX="${prefix}" "${PYTHON}" - "${RELEASE_JSON}" <<'PY'
import json, os, sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
prefix = os.environ["PREFIX"]
wheel = next(
    (a for a in data.get("assets", [])
     if a["name"].startswith(prefix) and a["name"].endswith(".whl")),
    None,
)
if wheel is None:
    sys.stderr.write(f"install.sh: no asset matching {prefix}*.whl in release\n")
    sys.exit(1)
checksum = next(
    (a for a in data.get("assets", [])
     if a["name"] == wheel["name"] + ".sha256"),
    None,
)
if checksum is None:
    sys.stderr.write(f"install.sh: no .sha256 asset for {wheel['name']!r}\n")
    sys.exit(1)
print(wheel["name"])
print(wheel["url"])
print(checksum["name"])
print(checksum["url"])
PY
  )
  local wheel_name wheel_url checksum_name checksum_url
  wheel_name=$(echo "${lines}" | sed -n '1p')
  wheel_url=$(echo "${lines}" | sed -n '2p')
  checksum_name=$(echo "${lines}" | sed -n '3p')
  checksum_url=$(echo "${lines}" | sed -n '4p')
  echo "Downloading ${wheel_name}..."
  gh_download_asset "${wheel_url}" "${WORK_DIR}/${wheel_name}"
  gh_download_asset "${checksum_url}" "${WORK_DIR}/${checksum_name}"
}

# --- Resolve release metadata (remote mode only) ---

WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT
RELEASE_JSON="${WORK_DIR}/release.json"

if [[ -z "${LOCAL_DIR}" ]]; then
  if [[ -z "${VERSION}" ]]; then
    gh_curl_json "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" "${RELEASE_JSON}"
    VERSION=$("${PYTHON}" -c "import json,sys; print(json.load(open(sys.argv[1]))['tag_name'])" "${RELEASE_JSON}")
  else
    VERSION="v${VERSION#v}"
    gh_curl_json "https://api.github.com/repos/${GITHUB_REPO}/releases/tags/${VERSION}" "${RELEASE_JSON}"
  fi
  echo "Installing ${TOOL_NAME} ${VERSION}..."
else
  echo "Installing ${TOOL_NAME} from ${LOCAL_DIR}..."
fi

# --- Acquire every wheel + checksum ---

for prefix in "${WORKSPACE_DEP_WHEEL_PREFIXES[@]}"; do
  acquire_wheel "${prefix}"
done
acquire_wheel "${SERVICE_WHEEL_PREFIX}"

# --- Verify checksums ---

echo "Verifying checksums..."
(
  cd "${WORK_DIR}"
  for checksum in *.sha256; do
    sha256_check "${checksum}"
  done
)

# --- Install into venv ---

echo "Installing into ${VENV_DIR}..."
mkdir -p "${INSTALL_DIR}"
"${PYTHON}" -m venv --clear "${VENV_DIR}"

# Pass workspace-dep wheels first so a reader can see the dep-first
# install order at a glance. pip's resolver actually treats every
# wheel passed in one ``pip install`` call as part of the same
# resolution set, so the order is cosmetic — but the explicit
# ordering documents intent.
WHEEL_ARGS=()
for prefix in "${WORKSPACE_DEP_WHEEL_PREFIXES[@]}"; do
  for whl in "${WORK_DIR}/${prefix}"*.whl; do
    WHEEL_ARGS+=("${whl}")
  done
done
for whl in "${WORK_DIR}/${SERVICE_WHEEL_PREFIX}"*.whl; do
  WHEEL_ARGS+=("${whl}")
done

"${VENV_DIR}/bin/pip" install --quiet --no-cache-dir --no-input "${WHEEL_ARGS[@]}"

# --- Symlink entrypoints ---

mkdir -p "${BIN_DIR}"
for entry in "${ENTRYPOINTS[@]}"; do
  link="${BIN_DIR}/${entry}"
  ln -sf "${VENV_DIR}/bin/${entry}" "${link}"
done

# --- Verify ---

primary_bin="${BIN_DIR}/${ENTRYPOINTS[0]}"
if ! "${primary_bin}" --version >/dev/null 2>&1; then
  echo "install.sh: installation verification failed — '${primary_bin} --version' did not exit 0." >&2
  exit 1
fi

echo
echo "${TOOL_NAME} installed successfully."
echo "  Venv:   ${VENV_DIR}"
echo "  Binaries:"
for entry in "${ENTRYPOINTS[@]}"; do
  echo "    ${BIN_DIR}/${entry}"
done

# --- PATH warning ---

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *)
    echo
    echo "Warning: ${BIN_DIR} is not on your PATH."
    echo "Add it to your shell profile, e.g.:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    ;;
esac

echo
echo "To uninstall, run:"
echo "  curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/${PACKAGE_SUBDIR}/install.sh | bash -s -- --uninstall"
