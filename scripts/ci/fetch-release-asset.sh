#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Download a GitHub release asset with authenticated curl + retry, then
# verify its sha256. Used by .github/actions/setup-toolchain to install CI
# tools (shellcheck, shfmt, ruff, taplo, keep-sorted, ripsecrets, treefmt)
# from a single code path so hardening (retry shape, auth header, mirror
# fallback) lives in one place.
#
# Usage: fetch-release-asset.sh <url> <out-path> <sha256>
#
# Requires GITHUB_TOKEN in the environment — authenticated download is the
# only supported path (shares the 5,000/hr token budget instead of the
# anonymous per-IP limit). Extraction and install are the caller's
# responsibility because binary shapes (.tar.xz, .tar.gz, .gz, raw) differ
# per tool.
#
# Auth is safe: curl -L strips the Authorization header on cross-origin
# redirects, so the bearer token only reaches github.com and never the
# S3 asset URL it redirects to. See #159.

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "fetch-release-asset: expected 3 args (url, out-path, sha256); got $#" >&2
  exit 2
fi

url="$1"
out_path="$2"
sha256="$3"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "fetch-release-asset: GITHUB_TOKEN must be set (authenticated download is required)." >&2
  exit 2
fi

# --retry-all-errors (curl 7.71+) is load-bearing: plain --retry skips HTTP
# 4xx, which is what GitHub rate-limit responses return. --retry-max-time
# bounds total retry wall-time and lets curl honour Retry-After and
# exponential backoff between attempts without an explicit --retry-delay.
curl -fsSL \
  --retry 5 \
  --retry-max-time 60 \
  --retry-all-errors \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o "${out_path}" \
  "${url}"

echo "${sha256}  ${out_path}" | sha256sum -c -
