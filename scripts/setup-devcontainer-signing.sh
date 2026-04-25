#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Wire commit signing inside the devcontainer to the host's gpg-bridge.
#
# Writes the gpg-cli config (bridge URL, the agent-auth refresh-capable
# credential pair, optional TLS CA path and timeout) to
# $XDG_CONFIG_HOME/gpg-cli/config.yaml with 0600 permissions, then runs
# `git config --local` to point git at `gpg-cli` and turn on
# auto-signing for every commit.
#
# Idempotent: re-running with the same inputs produces the same
# config file and git-config state.
#
# Token model: agent-auth issues a refresh-capable credential family
# (access token + refresh token + family id) on the host. The
# devcontainer-side gpg-cli holds the pair on disk and rotates it on
# every 401 token_expired (refresh) or refresh_token_expired (reissue,
# blocks on host-side JIT approval) — the operator only re-runs this
# script when a refresh / reissue terminally fails (reuse detected,
# family revoked, scope denied) and a fresh family must be minted.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup-devcontainer-signing.sh --access-token <T> --refresh-token <R> \
                                     --auth-url <URL> --bridge-url <URL> \
                                     [--family-id <ID>] \
                                     [--ca-cert-path <PATH>] \
                                     [--timeout-seconds <N>]

Required:
  --access-token <T>       agent-auth access token with the
                           `gpg:sign=allow` scope. Mint on the host
                           with `task agent-auth -- token create
                           --scope gpg:sign=allow --json` and copy the
                           `access_token` field.
  --refresh-token <R>      Companion refresh token from the same
                           token-create call (`refresh_token` field).
                           gpg-cli rotates this pair on 401
                           token_expired without operator action.
  --auth-url <URL>         https URL of the host's agent-auth service.
                           gpg-cli posts to /agent-auth/v1/token/refresh
                           and /agent-auth/v1/token/reissue here.
  --bridge-url <URL>       https URL of the host's gpg-bridge.

Optional:
  --family-id <ID>         Token family id (`family_id` field from
                           token-create). Required for the reissue
                           path (refresh-token expiry recovery via
                           host JIT approval); without it gpg-cli
                           exits with a clear instruction to re-run
                           this script.
  --ca-cert-path <PATH>    Path to a CA cert that signs the bridge's
                           and agent-auth's TLS certificates. Forwarded
                           to gpg-cli for both endpoints.
  --timeout-seconds <N>    Per-request timeout for gpg-cli ->
                           gpg-bridge. Defaults to gpg-cli's built-in
                           default.
  -h | --help              Show this help.
EOF
}

access_token=""
refresh_token=""
family_id=""
auth_url=""
bridge_url=""
ca_cert_path=""
timeout_seconds=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --access-token)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --access-token requires a value." >&2
        exit 1
      }
      access_token="$2"
      shift 2
      ;;
    --refresh-token)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --refresh-token requires a value." >&2
        exit 1
      }
      refresh_token="$2"
      shift 2
      ;;
    --family-id)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --family-id requires a value." >&2
        exit 1
      }
      family_id="$2"
      shift 2
      ;;
    --auth-url)
      [[ $# -ge 2 ]] || {
        echo "setup-devcontainer-signing: --auth-url requires a value." >&2
        exit 1
      }
      auth_url="$2"
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

if [[ -z "${access_token}" ]]; then
  echo "setup-devcontainer-signing: --access-token is required." >&2
  usage >&2
  exit 1
fi

if [[ -z "${refresh_token}" ]]; then
  echo "setup-devcontainer-signing: --refresh-token is required." >&2
  usage >&2
  exit 1
fi

if [[ -z "${auth_url}" ]]; then
  echo "setup-devcontainer-signing: --auth-url is required." >&2
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
  echo "# Re-run that script to regenerate. gpg-cli rewrites the"
  echo "# access_token / refresh_token fields after every refresh."
  echo "bridge_url: ${bridge_url}"
  echo "auth_url: ${auth_url}"
  echo "access_token: ${access_token}"
  echo "refresh_token: ${refresh_token}"
  if [[ -n "${family_id}" ]]; then
    echo "family_id: ${family_id}"
  fi
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

echo "setup-devcontainer-signing: wrote ${config_path}"
echo "setup-devcontainer-signing: set git config --local gpg.program=gpg-cli, commit.gpgsign=true"
echo "setup-devcontainer-signing: every 'git commit' in this clone now signs through gpg-bridge."
echo "setup-devcontainer-signing: gpg-cli auto-refreshes the access token; re-run this script only on a terminal refresh/reissue failure."
echo "setup-devcontainer-signing: override per-commit with 'git -c commit.gpgsign=false commit'."
