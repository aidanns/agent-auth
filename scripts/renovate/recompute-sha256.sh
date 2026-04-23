#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Renovate postUpgradeTask helper: fetch the linux x86_64 release asset
# for a freshly-bumped tool and rewrite the sibling `sha256_linux_x86_64`
# field in .github/tool-versions.yaml. Invoked as:
#
#   bash scripts/renovate/recompute-sha256.sh <depName> <newVersion>
#
# <depName> is the Renovate-side package name (e.g. `koalaman/shellcheck`);
# the manifest key and the asset URL are derived from it per the case
# statement below.
#
# Tools pinned in tool-versions.yaml that have no sha256 field
# (go-task, uv, mdformat*) are no-ops — Renovate bumps the version
# alone.
#
# Required on Renovate's runner: curl, yq (mikefarah v4), sha256sum.
# The command must be added to `allowedPostUpgradeCommands` on the
# Renovate installation's repo or org settings so Renovate will
# execute it. See ADR 0031.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "recompute-sha256: expected 2 args (depName, newVersion); got $#" >&2
  exit 2
fi

dep_name="$1"
new_version="$2"
manifest=".github/tool-versions.yaml"

# Map a Renovate depName / manifest key to:
#   1. The manifest key to update.
#   2. The URL template for the linux x86_64 release asset (uses
#      ${VERSION} literal).
case "${dep_name}" in
  koalaman/shellcheck | shellcheck)
    manifest_key="shellcheck"
    url_template="https://github.com/koalaman/shellcheck/releases/download/v\${VERSION}/shellcheck-v\${VERSION}.linux.x86_64.tar.xz"
    ;;
  mvdan/sh | shfmt)
    manifest_key="shfmt"
    url_template="https://github.com/mvdan/sh/releases/download/v\${VERSION}/shfmt_v\${VERSION}_linux_amd64"
    ;;
  astral-sh/ruff | ruff)
    manifest_key="ruff"
    url_template="https://github.com/astral-sh/ruff/releases/download/\${VERSION}/ruff-x86_64-unknown-linux-gnu.tar.gz"
    ;;
  tamasfe/taplo | taplo)
    manifest_key="taplo"
    url_template="https://github.com/tamasfe/taplo/releases/download/\${VERSION}/taplo-linux-x86_64.gz"
    ;;
  google/keep-sorted | keep-sorted)
    manifest_key="keep-sorted"
    url_template="https://github.com/google/keep-sorted/releases/download/v\${VERSION}/keep-sorted_linux"
    ;;
  sirwart/ripsecrets | ripsecrets)
    manifest_key="ripsecrets"
    url_template="https://github.com/sirwart/ripsecrets/releases/download/v\${VERSION}/ripsecrets-\${VERSION}-x86_64-unknown-linux-gnu.tar.gz"
    ;;
  numtide/treefmt | treefmt)
    manifest_key="treefmt"
    url_template="https://github.com/numtide/treefmt/releases/download/v\${VERSION}/treefmt_\${VERSION}_linux_amd64.tar.gz"
    ;;
  terrastruct/d2 | d2)
    manifest_key="d2"
    url_template="https://github.com/terrastruct/d2/releases/download/v\${VERSION}/d2-v\${VERSION}-linux-amd64.tar.gz"
    ;;
  # Tools without a sha256 pin (version-only): return 0 so Renovate
  # accepts the postUpgradeTask as a no-op.
  go-task/task | go-task | astral-sh/uv | uv | mdformat | mdformat-gfm | mdformat-tables)
    echo "recompute-sha256: ${dep_name} has no sha256 field; skipping." >&2
    exit 0
    ;;
  *)
    echo "recompute-sha256: unknown depName '${dep_name}' — teach the case statement or skip." >&2
    exit 1
    ;;
esac

# Substitute ${VERSION} in the template. Guarded against a misconfigured
# template that leaves the placeholder in place — the single-quoted
# literal below is deliberate (we're matching the sentinel, not
# expanding it).
url="${url_template//\$\{VERSION\}/${new_version}}"
# shellcheck disable=SC2016
if [[ "${url}" == *'${VERSION}'* ]]; then
  echo "recompute-sha256: URL template for '${dep_name}' failed to substitute VERSION: ${url_template}" >&2
  exit 1
fi

echo "recompute-sha256: downloading ${url}" >&2
tmp="$(mktemp -t renovate-sha256-XXXXXX)"
trap 'rm -f "${tmp}"' EXIT
curl -fsSL --retry 5 --retry-max-time 60 --retry-all-errors -o "${tmp}" "${url}"

new_sha256="$(sha256sum "${tmp}" | awk '{print $1}')"
if [[ ! "${new_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "recompute-sha256: computed sha256 is not 64 hex chars: '${new_sha256}'" >&2
  exit 1
fi

# Rewrite in place, touching only the sha256 line inside the matched
# tool's block. yq -i would correctly update the value but also
# reformats the file (strips blank lines between top-level entries),
# producing a noisy diff. awk targets the one line that needs to
# change.
tmp_out="$(mktemp -t renovate-sha256-out-XXXXXX)"
awk -v key="${manifest_key}" -v sha="${new_sha256}" '
  function starts_block(line, name,    first)
  {
    first = line
    sub(/[[:space:]]*#.*$/, "", first) # drop trailing comments
    return first == name ":"
  }
  /^[^ \t#]/ { in_block = starts_block($0, key) }
  in_block && /^[[:space:]]+sha256_linux_x86_64:[[:space:]]*"[0-9a-f]+"[[:space:]]*$/ {
    sub(/"[0-9a-f]+"/, "\"" sha "\"")
  }
  { print }
' "${manifest}" >"${tmp_out}"
mv "${tmp_out}" "${manifest}"

# Fail loud if the rewrite didn't actually change anything — means the
# regex or `starts_block` logic didn't match the current manifest
# shape.
if ! grep -qF "${new_sha256}" "${manifest}"; then
  echo "recompute-sha256: ${manifest_key}.sha256_linux_x86_64 was not rewritten; manifest layout may have changed." >&2
  exit 1
fi

echo "recompute-sha256: ${manifest_key} sha256_linux_x86_64 -> ${new_sha256}" >&2
