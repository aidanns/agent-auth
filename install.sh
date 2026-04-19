#!/usr/bin/env bash

# Install agent-auth, things-bridge, things-cli, and things-client-cli-applescript
# from the agent-auth GitHub repository into a uv-managed tool environment.

set -euo pipefail

REPO="aidanns/agent-auth"
GITHUB_URL="https://github.com/${REPO}"

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

# Resolve the latest release tag so users get the tagged version, not HEAD.
# Falls back to HEAD if no release has been cut yet.
LATEST_TAG="$(
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null \
    || true
)"

if [[ -n "${LATEST_TAG}" ]]; then
  INSTALL_SOURCE="git+${GITHUB_URL}.git@${LATEST_TAG}"
else
  INSTALL_SOURCE="git+${GITHUB_URL}.git"
fi

echo "Installing agent-auth ${LATEST_TAG:-HEAD} from ${GITHUB_URL} ..."
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
