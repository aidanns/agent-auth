#!/usr/bin/env bash

# Boot-prep for the macOS-Tart-VM smoke lane. Runs inside a clean
# `cirruslabs/macos-sequoia-base` guest under
# `.github/workflows/test-system-macos-tart.yml`. Installs Things 3,
# seeds an `kTCCServiceAppleEvents` Automation grant for `osascript`
# -> `com.culturedcode.ThingsMac` directly into TCC.db (SIP off in
# the cirruslabs base image makes this possible), bootstraps `uv`,
# and seeds a `ci-smoke-todo` to-do that the smoke test reads back
# through the AppleScript CLI. See ADR 0047 for the design rationale
# and `docs/operations/macos-tart-ci.md` for failure-mode debugging.

set -euo pipefail

ARTEFACT_DIR="${ARTEFACT_DIR:-/tmp/macos-tart-artefacts}"
mkdir -p "${ARTEFACT_DIR}"

# Mirror every step's stdout/stderr to a per-step log file so the
# failure-artefact bundle (rsynced back to the GitHub runner under
# `if: always()`) carries a clear breadcrumb trail. `tee -a` keeps
# the runner's own console log intact.
exec > >(tee -a "${ARTEFACT_DIR}/bootstrap.log") 2>&1

step() {
  echo
  echo "=== $* ==="
}

step "system_profiler / sw_vers (record runner OS for the artefact bundle)"
sw_vers | tee "${ARTEFACT_DIR}/sw_vers.txt"
system_profiler SPSoftwareDataType >"${ARTEFACT_DIR}/system_profiler.txt"

step "1. install homebrew if missing"
if ! command -v brew >/dev/null 2>&1; then
  # The Homebrew install script body is unverified by us — there is
  # no published checksum that travels independently of the script
  # itself. Acceptable here because (a) this runs inside a throwaway
  # VM that holds no secrets, (b) the alternative (bootstrapping a
  # static brew tarball) is materially more brittle for cask
  # installs, and (c) per ADR 0047 the Tart base image is intended
  # to evolve toward Option A (#568) which would bake brew + Things 3
  # into the image and remove this surface entirely.
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Apple Silicon installs land at /opt/homebrew; ensure brew is on
  # PATH for the rest of the script.
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
brew --version

step "2. brew install --cask things"
# The cask floats on the upstream Cultured Code release channel —
# pinning is not viable without re-distributing the binary, so the
# trade-off is "brew install --cask things sometimes gets a fresher
# Things 3 than the smoke test was last verified against". When that
# breaks the smoke test it surfaces here; see
# `docs/operations/macos-tart-ci.md` -> "Things 3 dictionary
# breakage" for the diagnosis recipe.
brew install --cask things

step "3. seed the kTCCServiceAppleEvents grant in TCC.db"
# The cirruslabs `macos-sequoia-base` image ships with SIP off so
# we can write directly to TCC.db. On Sequoia, tccd runs in both
# user and system domains; both must be unloaded before a sqlite3
# write or tccd will overwrite the row from its in-memory cache on
# the next sync.
sudo launchctl unload /System/Library/LaunchAgents/com.apple.tccd.plist 2>/dev/null || true
sudo launchctl bootout system /System/Library/LaunchDaemons/com.apple.tccd.plist 2>/dev/null || true

TCC_DB="/Library/Application Support/com.apple.TCC/TCC.db"

# The Sequoia `access` table column set is documented in
# `docs/operations/macos-tart-ci.md` -> "TCC.db schema". Auth values:
#   service                            = `kTCCServiceAppleEvents` (Automation)
#   client                             = `/usr/bin/osascript`
#   client_type                        = 1 (path-based identifier)
#   auth_value                         = 2 (allow)
#   auth_reason                        = 3 (user-set; closest match for "operator-seeded")
#   auth_version                       = 1
#   csreq                              = NULL — Sequoia accepts a NULL csreq for
#                                        path-based grants when the client column
#                                        carries a stable absolute path. Using
#                                        NULL here keeps the seed forward-
#                                        compatible across Sequoia minor versions
#                                        whose csreq blob format may drift.
#   policy_id                          = NULL
#   indirect_object_identifier_type    = 0 (bundle id)
#   indirect_object_identifier         = `com.culturedcode.ThingsMac`
#   indirect_object_code_identity      = NULL (same forward-compat reasoning)
#   flags                              = 0
#   last_modified                      = current epoch seconds
#   pid / pid_version / boot_uuid      = NULL
#   last_reminded                      = 0
sudo sqlite3 "${TCC_DB}" <<'SQL'
INSERT OR REPLACE INTO access (
  service, client, client_type, auth_value, auth_reason, auth_version,
  csreq, policy_id,
  indirect_object_identifier_type, indirect_object_identifier,
  indirect_object_code_identity,
  flags, last_modified, pid, pid_version, boot_uuid, last_reminded
) VALUES (
  'kTCCServiceAppleEvents', '/usr/bin/osascript', 1, 2, 3, 1,
  NULL, NULL,
  0, 'com.culturedcode.ThingsMac',
  NULL,
  0, strftime('%s','now'), NULL, NULL, 'UNKNOWN', 0
);
SQL

# `sudo > file` writes the file as the unprivileged user, which is
# fine here because ${ARTEFACT_DIR} is owned by `admin` — but pipe
# through `cat` to keep `shellcheck` (SC2024) happy and to make the
# auth boundary explicit.
sudo sqlite3 "${TCC_DB}" \
  "SELECT * FROM access WHERE service = 'kTCCServiceAppleEvents';" \
  | cat >"${ARTEFACT_DIR}/tcc-grant-row.txt"
sudo sqlite3 "${TCC_DB}" ".schema access" \
  | cat >"${ARTEFACT_DIR}/tcc-access-schema.txt"

# Restart tccd in both domains.
sudo launchctl load /System/Library/LaunchAgents/com.apple.tccd.plist 2>/dev/null || true
sudo launchctl bootstrap system /System/Library/LaunchDaemons/com.apple.tccd.plist 2>/dev/null || true

# Give tccd a beat to pick up the row before the probe.
sleep 2

step "4. probe TCC grant by counting to-dos"
# This is the fail-fast gate: if the seed row didn't take effect
# (schema drift, tccd lock-out, Things 3 not yet first-launched
# enough for AppleScript to bind), we want to die here rather than
# in the smoke test where the failure mode is harder to diagnose.
# Things 3 must have been launched at least once for `tell
# application "Things3"` to bind — `open -a` triggers that without
# requiring a UI session.
open -a Things3 || true
sleep 5

probe_output=$(osascript -e 'tell application "Things3" to count to dos' \
  2> >(tee "${ARTEFACT_DIR}/tcc-probe.stderr" >&2))
echo "TCC probe -> count to dos = ${probe_output}"

step "5. install uv and sync the workspace venv"
# uv's official install script. Same caveat as the Homebrew install
# above: throwaway VM, no secrets at risk.
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="${HOME}/.local/bin:${PATH}"
export UV_PROJECT_ENVIRONMENT=".venv-Darwin-arm64"
uv --version
uv sync --extra dev

step "6. seed ci-smoke-todo into Things 3"
# Wrap the seed call in `set -x` so the artefact bundle's
# bootstrap.log carries the literal AppleScript invocation — useful
# when an upstream Things 3 update changes the AppleScript dictionary
# enough that the seed silently no-ops.
(
  set -x
  osascript -e \
    'tell application "Things3" to make new to do with properties {name:"ci-smoke-todo"}'
)

step "boot-prep complete"
