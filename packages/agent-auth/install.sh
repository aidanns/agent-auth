#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Install or upgrade ``agent-auth`` (the token server, token CLI, and
# the out-of-process approval notifier) from the monorepo into a
# uv-managed tool environment. Optionally uninstall with
# ``--uninstall``.
#
# Under issue #105 each service in the ``aidanns/agent-auth`` monorepo
# has its own installer; running this script installs only the
# ``agent-auth`` package and its transitive dependencies (including
# the ``agent-auth-common`` workspace package).

set -euo pipefail

GITHUB_REPO="aidanns/agent-auth"
GITHUB_URL="https://github.com/${GITHUB_REPO}"
TOOL_NAME="agent-auth"
PACKAGE_SUBDIR="packages/agent-auth"

# --- Argument parsing ---

VERSION=""
UNINSTALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      UNINSTALL=true
      shift
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
  uv tool uninstall "${TOOL_NAME}" 2>/dev/null || true
  echo "Done."
  echo
  echo "To reinstall, run:"
  echo "  curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/${PACKAGE_SUBDIR}/install.sh | bash"
  exit 0
fi

# --- Prerequisite checks ---

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
install.sh: 'uv' is required but not found on PATH.

Install uv first:
  macOS (Homebrew):  brew install uv
  Linux / macOS:     curl -LsSf https://astral.sh/uv/install.sh | sh

Then re-run this script.
EOF
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "install.sh: 'python3' is required to resolve the latest release tag." >&2
  exit 1
fi

# --- Resolve version ---

if [[ -z "${VERSION}" ]]; then
  VERSION="$(
    curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null \
      || true
  )"
fi

# ``uv tool install`` accepts a ``git+...`` URL with a
# ``#subdirectory=...`` fragment so we can install just the service
# package while its transitive workspace deps resolve from the same
# clone.
if [[ -n "${VERSION}" ]]; then
  INSTALL_SOURCE="git+${GITHUB_URL}.git@${VERSION}#subdirectory=${PACKAGE_SUBDIR}"
else
  INSTALL_SOURCE="git+${GITHUB_URL}.git#subdirectory=${PACKAGE_SUBDIR}"
fi

# --- Install ---

echo "Installing ${TOOL_NAME} ${VERSION:-HEAD} from ${GITHUB_URL} ..."
uv tool install --force "${INSTALL_SOURCE}"

# --- Verify ---

if ! command -v "${TOOL_NAME}" >/dev/null 2>&1; then
  echo "install.sh: installation verification failed — '${TOOL_NAME}' not found on PATH." >&2
  echo "  Run 'uv tool update-shell' to add the uv tool bin directory to your PATH." >&2
  exit 1
fi

echo
echo "Installation complete. The following commands are now available:"
echo "  agent-auth          — token lifecycle management and HTTP server"
echo "  agent-auth-notifier — out-of-process approval notifier sidecar"

# --- PATH warning ---

uv_bin_dir="$(uv tool dir)/bin"
case ":${PATH}:" in
  *":${uv_bin_dir}:"*) ;;
  *)
    echo
    echo "Warning: ${uv_bin_dir} may not be in your PATH."
    echo "Run the following to add it permanently:"
    echo "  uv tool update-shell"
    ;;
esac

echo
echo "To uninstall, run:"
echo "  curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/${PACKAGE_SUBDIR}/install.sh | bash -s -- --uninstall"
