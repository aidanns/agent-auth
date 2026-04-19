#!/usr/bin/env bash

# Install agent-auth, things-bridge, things-cli, and things-client-cli-applescript
# from the agent-auth GitHub repository into a uv-managed tool environment.

set -euo pipefail

REPO="aidanns/agent-auth"
INSTALL_SOURCE="git+https://github.com/${REPO}.git"

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

echo "Installing agent-auth from ${INSTALL_SOURCE} ..."
uv tool install --force "${INSTALL_SOURCE}"

echo
echo "Installation complete. The following commands are now available:"
echo "  agent-auth                  — token lifecycle management and HTTP server"
echo "  things-bridge               — Things 3 bridge HTTP server"
echo "  things-cli                  — Things 3 client (via things-bridge)"
echo "  things-client-cli-applescript — direct Things 3 CLI (macOS only)"
echo
echo "If the commands are not on PATH, run:"
echo "  uv tool update-shell"
