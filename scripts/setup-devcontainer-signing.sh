#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Wire commit signing inside the devcontainer to the host's gpg-bridge.
#
# Writes the gpg-cli config (bridge URL, bearer token, optional TLS
# CA path and timeout) to $XDG_CONFIG_HOME/gpg-cli/config.yaml with
# 0600 permissions, then runs `git config --local` to point git at
# `gpg-cli` and turn on auto-signing for every commit.
#
# After writing the config, runs an end-to-end smoke test that
# verifies (1) gpg-cli is on PATH, (2) git is configured with a
# signing-key fingerprint, (3) the bridge URL is reachable, and (4)
# a trial sign through gpg-cli succeeds. Each failure mode prints a
# named cause and a remediation hint, and exits non-zero so the
# operator does not discover the breakage at first `git commit`.
# Pass `--skip-smoke` to bypass the smoke test (e.g. when the
# bridge is not yet running, or in CI provisioning).
#
# Idempotent: re-running with the same inputs produces the same
# config file and git-config state, and re-runs the smoke test
# against the existing config.
#
# The agent-auth keyring lives on the host, so the bearer token is
# minted on the host (e.g. `task agent-auth -- token create
# --scope gpg:sign=allow --json`) and pasted into the
# devcontainer-side invocation of this script — see CONTRIBUTING.md
# § "Signed commits inside the devcontainer".

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup-devcontainer-signing.sh --token <TOKEN> --bridge-url <URL> \
                                     [--signing-key <FP>] \
                                     [--ca-cert-path <PATH>] \
                                     [--timeout-seconds <N>] \
                                     [--skip-smoke]

Required:
  --token <TOKEN>          agent-auth access token with the
                           `gpg:sign=allow` scope. Mint on the host
                           with `task agent-auth -- token create
                           --scope gpg:sign=allow --json`.
  --bridge-url <URL>       https URL of the host's gpg-bridge.

Optional:
  --signing-key <FP>       GPG key fingerprint git should sign with.
                           Written via `git config --local
                           user.signingkey`. If git already has a
                           local user.signingkey set, this flag is
                           optional. Required for the smoke test
                           when no local user.signingkey exists.
  --ca-cert-path <PATH>    Path to a CA cert that signs the bridge's
                           TLS certificate. Forwarded to gpg-cli.
  --timeout-seconds <N>    Per-request timeout for gpg-cli -> gpg-bridge.
                           Defaults to gpg-cli's built-in default.
  --skip-smoke             Skip the post-install smoke test. Use only
                           when the bridge is not reachable at install
                           time (e.g. CI provisioning); the install is
                           unverified and the operator finds out at
                           first `git commit`. See CONTRIBUTING.md §
                           "Signed commits inside the devcontainer".
  -h | --help              Show this help.
EOF
}

token=""
bridge_url=""
signing_key=""
ca_cert_path=""
timeout_seconds=""
skip_smoke=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --token requires a value." >&2
        exit 1
      }
      token="$2"
      shift 2
      ;;
    --bridge-url)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --bridge-url requires a value." >&2
        exit 1
      }
      bridge_url="$2"
      shift 2
      ;;
    --signing-key)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --signing-key requires a value." >&2
        exit 1
      }
      signing_key="$2"
      shift 2
      ;;
    --ca-cert-path)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --ca-cert-path requires a value." >&2
        exit 1
      }
      ca_cert_path="$2"
      shift 2
      ;;
    --timeout-seconds)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --timeout-seconds requires a value." >&2
        exit 1
      }
      timeout_seconds="$2"
      shift 2
      ;;
    --skip-smoke)
      skip_smoke=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "setup-devcontainer-signing: unknown argument '$1'." >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${token}" ]]; then
  echo "setup-devcontainer-signing: --token is required." >&2
  usage >&2
  exit 1
fi

if [[ -z "${bridge_url}" ]]; then
  echo "setup-devcontainer-signing: --bridge-url is required." >&2
  usage >&2
  exit 1
fi

if [[ -n "${timeout_seconds}" ]]; then
  if ! [[ "${timeout_seconds}" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "setup-devcontainer-signing: --timeout-seconds must be a number, got '${timeout_seconds}'." >&2
    exit 1
  fi
fi

if ! command -v git >/dev/null 2>&1; then
  echo "setup-devcontainer-signing: 'git' is not on PATH." >&2
  exit 1
fi

# `git config --local` requires being inside a git working tree.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "setup-devcontainer-signing: must be run inside a git working tree (so 'git config --local' has somewhere to write)." >&2
  exit 1
fi

config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/gpg-cli"
config_path="${config_dir}/config.yaml"

mkdir -p "${config_dir}"

# Write to a temp file in the same directory then rename, so a
# concurrent reader never sees a partial file. The temp file inherits
# the directory's mode; chmod before the rename so the final file
# carries 0600 from the moment it appears at config_path.
tmp_path="$(mktemp "${config_dir}/.config.yaml.XXXXXX")"
trap 'rm -f "${tmp_path}"' EXIT

{
  # The generated file lives outside the repo (in the user's
  # XDG_CONFIG_HOME) so it doesn't need a REUSE/SPDX header. A short
  # provenance comment is enough — it tells the next reader where the
  # file came from and how to regenerate it.
  echo "# Generated by scripts/setup-devcontainer-signing.sh."
  echo "# Re-run that script to regenerate."
  echo "bridge_url: ${bridge_url}"
  echo "token: ${token}"
  if [[ -n "${ca_cert_path}" ]]; then
    echo "ca_cert_path: ${ca_cert_path}"
  fi
  if [[ -n "${timeout_seconds}" ]]; then
    echo "timeout_seconds: ${timeout_seconds}"
  fi
} >"${tmp_path}"

chmod 0600 "${tmp_path}"
mv "${tmp_path}" "${config_path}"
trap - EXIT

git config --local gpg.program gpg-cli
git config --local commit.gpgsign true

# If the operator passed --signing-key, write it now (overwriting any
# existing value) so the smoke test below has a key to sign with and
# subsequent `git commit` calls don't fail before reaching gpg-cli.
if [[ -n "${signing_key}" ]]; then
  git config --local user.signingkey "${signing_key}"
fi

echo "setup-devcontainer-signing: wrote ${config_path}"
echo "setup-devcontainer-signing: set git config --local gpg.program=gpg-cli, commit.gpgsign=true"

if [[ "${skip_smoke}" -eq 1 ]]; then
  echo "setup-devcontainer-signing: WARNING --skip-smoke set; install is unverified." >&2
  echo "setup-devcontainer-signing: every 'git commit' in this clone now signs through gpg-bridge."
  echo "setup-devcontainer-signing: override per-commit with 'git -c commit.gpgsign=false commit'."
  exit 0
fi

# ----------------------------------------------------------------------
# Smoke test — probes 1..4. Each probe fails loudly with a named cause
# rather than letting the operator discover the breakage at first
# `git commit`. See issue #333 for the failure-mode catalogue.
# ----------------------------------------------------------------------

# Probe 1: gpg.program resolution. We just told git to use `gpg-cli`,
# which means git's child process will look it up on PATH. If the
# binary isn't on PATH, every future `git commit` blows up before it
# can talk to the bridge.
if ! command -v gpg-cli >/dev/null 2>&1; then
  echo "setup-devcontainer-signing: probe failed: gpg.program unresolved." >&2
  echo "setup-devcontainer-signing: 'gpg-cli' is not on PATH; git's gpg.program=gpg-cli will fail at commit time." >&2
  echo "setup-devcontainer-signing: install gpg-cli inside the devcontainer (see CONTRIBUTING.md § 'Signed commits inside the devcontainer')." >&2
  exit 1
fi

# Probe 2: user.signingkey. Without this, `git commit` fails before
# gpg-cli is even invoked — git can't pass `-u <key>` to its
# gpg.program if it doesn't know which key to sign with.
configured_signing_key="$(git config --local --get user.signingkey || true)"
if [[ -z "${configured_signing_key}" ]]; then
  echo "setup-devcontainer-signing: probe failed: user.signingkey is unset." >&2
  echo "setup-devcontainer-signing: pass --signing-key <FP> so this script can write 'git config --local user.signingkey'." >&2
  echo "setup-devcontainer-signing: without it, 'git commit' fails before reaching gpg-cli." >&2
  exit 1
fi

# Probe 3: bridge reachability. Any HTTP response (200, 401, 403, ...)
# proves the URL is reachable from this container; a connection error
# or timeout means the URL is wrong (e.g. 127.0.0.1 instead of
# host.docker.internal on Docker Desktop) or the bridge is down. We
# deliberately *don't* check the response code — the operator's token
# is `gpg:sign`-scoped, not `gpg-bridge:health`, so a 403 here is
# expected and not a failure. Probe 4 (trial sign) checks auth.
if ! command -v curl >/dev/null 2>&1; then
  echo "setup-devcontainer-signing: probe failed: 'curl' is not on PATH (needed for the bridge reachability probe)." >&2
  exit 1
fi

# All probe temp files live under one directory so a single trap
# tears every one down on any exit path (success, failure, signal).
# Using a directory rather than tracking individual paths keeps the
# trap idempotent across the multiple probes below.
probe_tmpdir="$(mktemp -d)"
# shellcheck disable=SC2064 # capture path at trap-set time, not when fired
trap "rm -rf '${probe_tmpdir}'" EXIT

reachability_url="${bridge_url%/}/gpg-bridge/health"
curl_args=(
  --silent
  --output /dev/null
  --connect-timeout 5
  --max-time 10
  --write-out '%{http_code}'
)
if [[ -n "${ca_cert_path}" ]]; then
  curl_args+=(--cacert "${ca_cert_path}")
fi

# Write the auth header to a 0600 temp file and pass it to curl via
# `--header @file` so the bearer token never appears on the curl argv
# (where every local account could see it via `ps auxww`). /health
# doesn't strictly need the header (probe only cares about
# reachability, not status code), but attaching it keeps the request
# shape identical to a real probe and proves the cert chain works for
# an authenticated request too.
auth_header_path="${probe_tmpdir}/auth-header"
(umask 0077 && printf 'Authorization: Bearer %s\n' "${token}" >"${auth_header_path}")

http_status=""
if ! http_status="$(curl "${curl_args[@]}" \
  --header "@${auth_header_path}" \
  "${reachability_url}" 2>/dev/null)"; then
  echo "setup-devcontainer-signing: probe failed: bridge unreachable at ${bridge_url}." >&2
  echo "setup-devcontainer-signing: check the bridge is running on the host and the URL is reachable from this container." >&2
  echo "setup-devcontainer-signing: on Docker Desktop, prefer 'host.docker.internal' over '127.0.0.1' (which resolves to the container's loopback)." >&2
  echo "setup-devcontainer-signing: see docs/operations/gpg-bridge-host-setup.md for host-side troubleshooting." >&2
  exit 1
fi

if [[ -z "${http_status}" || "${http_status}" == "000" ]]; then
  echo "setup-devcontainer-signing: probe failed: bridge unreachable at ${bridge_url} (no HTTP response)." >&2
  echo "setup-devcontainer-signing: check the bridge is running and TLS is configured (HTTP 000 means curl could not complete the request)." >&2
  echo "setup-devcontainer-signing: see docs/operations/gpg-bridge-host-setup.md for host-side troubleshooting." >&2
  exit 1
fi

# Probe 4: end-to-end trial sign. Drives the full path that `git
# commit` will use — gpg-cli reads the config we just wrote, dials
# the bridge, the bridge re-checks the token's scope and key
# allowlist, and the host gpg signs a constant payload. Each gpg-cli
# exit code below maps to a specific failure mode; see ADR 0033 and
# packages/gpg-cli/src/gpg_cli/cli.py for the exit code catalogue.
trial_payload="setup-devcontainer-signing smoke test"
trial_stderr_path="${probe_tmpdir}/trial-stderr"
trial_stdout_path="${probe_tmpdir}/trial-stdout"

trial_exit=0
printf '%s\n' "${trial_payload}" \
  | gpg-cli --status-fd 2 -bsau "${configured_signing_key}" \
    >"${trial_stdout_path}" 2>"${trial_stderr_path}" \
  || trial_exit=$?

case "${trial_exit}" in
  0)
    if ! grep -q '\[GNUPG:\] SIG_CREATED' "${trial_stderr_path}"; then
      echo "setup-devcontainer-signing: probe failed: trial sign exited 0 but produced no SIG_CREATED status line." >&2
      echo "--- gpg-cli stderr ---" >&2
      cat "${trial_stderr_path}" >&2
      echo "----------------------" >&2
      exit 1
    fi
    echo "setup-devcontainer-signing: trial sign succeeded with key ${configured_signing_key}"
    ;;
  3)
    echo "setup-devcontainer-signing: probe failed: bridge rejected the token (unauthorized)." >&2
    echo "setup-devcontainer-signing: mint a new one on the host with 'task agent-auth -- token create --scope gpg:sign=allow --json'." >&2
    exit 1
    ;;
  4)
    echo "setup-devcontainer-signing: probe failed: bridge accepted the token but denied the request (forbidden)." >&2
    echo "setup-devcontainer-signing: causes: token lacks gpg:sign=allow, or signing key ${configured_signing_key} is not in the bridge's allowed_signing_keys list." >&2
    echo "setup-devcontainer-signing: see docs/operations/gpg-bridge-host-setup.md § 'allowed_signing_keys'." >&2
    exit 1
    ;;
  5)
    # TODO(#331): once the fail-fast on wedged backend subprocess
    # change lands, gpg-cli will surface a distinct
    # `signing_backend_unavailable` code; remap the message here to
    # point specifically at host gpg-agent / `allow-loopback-pinentry`.
    echo "setup-devcontainer-signing: probe failed: bridge unavailable (host gpg-bridge or its backend could not complete the request)." >&2
    echo "setup-devcontainer-signing: causes: bridge subprocess timed out, host gpg-agent passphrase prompt blocked, or no 'allow-loopback-pinentry'." >&2
    echo "setup-devcontainer-signing: see docs/operations/gpg-bridge-host-setup.md for host-side gpg-agent troubleshooting." >&2
    exit 1
    ;;
  *)
    echo "setup-devcontainer-signing: probe failed: gpg-cli exited ${trial_exit}." >&2
    echo "--- gpg-cli stderr ---" >&2
    cat "${trial_stderr_path}" >&2
    echo "----------------------" >&2
    echo "setup-devcontainer-signing: see docs/operations/gpg-bridge-host-setup.md for known failure modes." >&2
    exit 1
    ;;
esac

# Probe-temp directory is cleaned up by the EXIT trap installed at
# the top of the smoke test.

echo "setup-devcontainer-signing: every 'git commit' in this clone now signs through gpg-bridge."
echo "setup-devcontainer-signing: override per-commit with 'git -c commit.gpgsign=false commit'."
