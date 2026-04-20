#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Install or upgrade agent-auth, things-bridge, things-cli, and
# things-client-cli-applescript from a GitHub release into a uv-managed tool
# environment. Optionally uninstall with --uninstall.

set -euo pipefail

GITHUB_REPO="aidanns/agent-auth"
GITHUB_URL="https://github.com/${GITHUB_REPO}"

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
  echo "Uninstalling agent-auth..."
  uv tool uninstall agent-auth 2>/dev/null || true
  echo "Done."
  echo
  echo "To reinstall, run:"
  echo "  curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/install.sh | bash"
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

if [[ -n "${VERSION}" ]]; then
  INSTALL_SOURCE="git+${GITHUB_URL}.git@${VERSION}"
else
  INSTALL_SOURCE="git+${GITHUB_URL}.git"
fi

# --- Install ---

echo "Installing agent-auth ${VERSION:-HEAD} from ${GITHUB_URL} ..."
uv tool install --force "${INSTALL_SOURCE}"

# --- Verify ---

if ! command -v agent-auth >/dev/null 2>&1; then
  echo "install.sh: installation verification failed — 'agent-auth' not found on PATH." >&2
  echo "  Run 'uv tool update-shell' to add the uv tool bin directory to your PATH." >&2
  exit 1
fi

echo
echo "Installation complete. The following commands are now available:"
echo "  agent-auth                    — token lifecycle management and HTTP server"
echo "  things-bridge                 — Things 3 bridge HTTP server"
echo "  things-cli                    — Things 3 client (via things-bridge)"
echo "  things-client-cli-applescript — direct Things 3 CLI (macOS only)"

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
echo "  curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/install.sh | bash -s -- --uninstall"
