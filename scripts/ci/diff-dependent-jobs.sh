#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Print the list of GitHub check-run names whose outcome depends only on
# the code at the PR's head SHA — the "diff-dependent" set, distinct from
# checks that read PR metadata (labels, title, body, milestone).
#
# Used by the `plan` job in `.github/workflows/ci.yml` (issue #527 /
# Option 4 — verified partial re-run on label-only events). On a
# `labeled` / `unlabeled` event the head SHA is the same as the prior
# `synchronize`, so any check-run that already produced `success` on
# that SHA is still authoritative; those checks can skip and the
# aggregator's `skipped = failure` rule (#441) is relaxed for them
# specifically.
#
# Derivation: read `ci.yml`'s `required-checks-passed.needs:` array,
# subtract the planning job (`plan`) and the metadata-dependent
# allowlist, then walk each surviving ci.yml job's `uses:` workflow
# file and enumerate its job leaves. For nested `workflow_call`
# chains, recurse through the `uses:` link and emit
# `<top> / <mid> / <leaf>`; for matrix jobs, expand rows by reading the
# `matrix:` block. Driving this from `yq` over the workflow files
# means a new child or matrix row added to ci.yml extends the probe
# set automatically — no hand-edited case statement to drift.
#
# Usage:
#   scripts/ci/diff-dependent-jobs.sh [path-to-ci.yml]
#
# Default ci.yml path is `.github/workflows/ci.yml` relative to the
# repo root (auto-detected via the script's own location).
#
# Output: one check-run name per line on stdout. Requires `yq`
# (Mike Farah's Go yq) and `jq`, both already in the repo's required
# tooling per CLAUDE.md and `scripts/verify-dependencies.sh`.

set -euo pipefail

if [[ $# -gt 1 ]]; then
  echo "diff-dependent-jobs: expected at most 1 arg (path to ci.yml); got $#" >&2
  exit 2
fi

# Repo root resolved from the script's own location so callers can
# invoke from any cwd (the `plan` job runs from the workspace root,
# but tests may invoke from elsewhere).
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../.." && pwd)
ci_yml="${1:-${repo_root}/.github/workflows/ci.yml}"

if [[ ! -f "${ci_yml}" ]]; then
  echo "diff-dependent-jobs: ci.yml not found at: ${ci_yml}" >&2
  exit 2
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "diff-dependent-jobs: yq is required but not installed" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "diff-dependent-jobs: jq is required but not installed" >&2
  exit 2
fi

# Metadata-dependent ci.yml job IDs. Their outcome may change
# between label events on the same head SHA, so they MUST re-run
# unconditionally. Default for any new child is "diff-dependent" —
# only add a job here if its evaluation reads PR metadata
# (labels, title, body, milestone, etc.).
metadata_dependent=(
  check-changelog
  check-pull-request
)

# Convert a workflow file into a JSON document for jq consumption.
# Mike Farah's yq supports `-o=json`; this lets the rest of the
# script use jq's full conditional-expression vocabulary.
wf_json() {
  yq -o=json '.' "$1"
}

# Resolve a `uses: ./.github/workflows/<name>.yml` value to an
# absolute file path under the workflows dir. Empty string for
# non-local `uses:` (e.g. `org/repo/.github/workflows/x.yml@ref`).
resolve_local_uses() {
  local uses="$1"
  if [[ "${uses}" == "./.github/workflows/"* ]]; then
    echo "${repo_root}/${uses#./}"
  fi
}

# Emit the matrix-expanded leaf-name suffix(es) for a job.
# - No matrix: emits a single empty line so the caller treats it as
#   one non-matrixed leaf.
# - Single-key matrix with scalar rows: emits `(<row>)` per row.
# - Single-key matrix with object rows: emits `(<v1>, <v2>, ...)`
#   per row, joining the object's values in declared order.
# Multi-key matrices are not currently used in this repo; if one
# lands the helper exits non-zero so the extension is explicit.
matrix_suffixes() {
  local wf_json_doc="$1"
  local jid="$2"
  local matrix_json
  matrix_json=$(echo "${wf_json_doc}" | jq --arg jid "${jid}" '.jobs[$jid].strategy.matrix // empty')
  if [[ -z "${matrix_json}" ]]; then
    echo ""
    return 0
  fi
  # Filter out `include` / `exclude` keys; everything else is a row dimension.
  local row_keys
  row_keys=$(echo "${matrix_json}" \
    | jq -r 'keys[] | select(. != "include" and . != "exclude")')
  local key_count
  key_count=$(printf '%s\n' "${row_keys}" | awk 'NF' | wc -l)
  if [[ "${key_count}" -eq 0 ]]; then
    echo ""
    return 0
  fi
  if [[ "${key_count}" -gt 1 ]]; then
    echo "diff-dependent-jobs: multi-key matrix in ${jid} not supported; extend matrix_suffixes()" >&2
    exit 2
  fi
  local key
  key=$(printf '%s\n' "${row_keys}" | awk 'NF' | head -n 1)
  echo "${matrix_json}" \
    | jq -r --arg k "${key}" '
        .[$k][] |
        if (type == "object")
          then "(" + ([.[] | tostring] | join(", ")) + ")"
          else "(" + tostring + ")"
        end'
}

# Enumerate the check-run name suffix(es) for a job in a workflow.
# - Direct (`runs-on:`) job: emits `<base> [<matrix-suffix>]` per
#   matrix row, where `<base>` is the job's `name:` template
#   (with the matrix placeholder stripped) or the job ID.
# - `uses:` workflow_call job: recurses into the called workflow
#   and prefixes every leaf with `<jid> / `.
emit_job_leaves() {
  local wf="$1"
  local jid="$2"
  local wf_doc
  wf_doc=$(wf_json "${wf}")
  local uses
  uses=$(echo "${wf_doc}" | jq -r --arg jid "${jid}" '.jobs[$jid].uses // ""')
  if [[ -n "${uses}" ]]; then
    local called
    called=$(resolve_local_uses "${uses}")
    if [[ -z "${called}" || ! -f "${called}" ]]; then
      echo "diff-dependent-jobs: cannot resolve workflow_call uses=${uses} in ${wf}" >&2
      exit 2
    fi
    local sub
    while IFS= read -r sub; do
      [[ -z "${sub}" ]] && continue
      echo "${jid} / ${sub}"
    done < <(emit_workflow_leaves "${called}")
    return 0
  fi
  # Direct job. Pull `name:` template if set, else fall back to job ID.
  local name
  name=$(echo "${wf_doc}" | jq -r --arg jid "${jid}" '.jobs[$jid].name // ""')
  local base
  if [[ -n "${name}" ]]; then
    # Strip `(${{ matrix.<key> }})` from the template; matrix_suffixes()
    # reattaches the row-specific parens-suffix below.
    base=$(echo "${name}" | sed -E 's/[[:space:]]*\(\$\{\{[[:space:]]*matrix\.[^}]+\}\}[[:space:]]*\)//')
  else
    base="${jid}"
  fi
  local suffix
  while IFS= read -r suffix; do
    if [[ -n "${suffix}" ]]; then
      echo "${base} ${suffix}"
    else
      echo "${base}"
    fi
  done < <(matrix_suffixes "${wf_doc}" "${jid}")
}

# Enumerate every leaf check-run name produced by a workflow file.
# Skips jobs named `required-checks-passed` (defence-in-depth — none
# should remain in the tree after this PR).
emit_workflow_leaves() {
  local wf="$1"
  local wf_doc
  wf_doc=$(wf_json "${wf}")
  local jids
  jids=$(echo "${wf_doc}" | jq -r '.jobs | keys[]')
  local jid
  for jid in ${jids}; do
    if [[ "${jid}" == "required-checks-passed" ]]; then
      continue
    fi
    emit_job_leaves "${wf}" "${jid}"
  done
}

# Read `required-checks-passed.needs:` as a flat list, one job ID per
# line.
needs=$(yq -r '.jobs."required-checks-passed".needs[]' "${ci_yml}")

# Apply the subtractions (`plan` + metadata-dependent set) using
# associative-array set membership so the script remains O(n).
declare -A excluded=([plan]=1)
for j in "${metadata_dependent[@]}"; do
  excluded["${j}"]=1
done

# Iterate the surviving job IDs in the order ci.yml lists them. Order
# is stable so the script's stdout is deterministic; the tests rely on
# this for golden-file comparisons.
diff_dependent_job_ids=()
while IFS= read -r jid; do
  [[ -z "${jid}" ]] && continue
  if [[ -z "${excluded["${jid}"]+x}" ]]; then
    diff_dependent_job_ids+=("${jid}")
  fi
done <<<"${needs}"

for jid in "${diff_dependent_job_ids[@]}"; do
  emit_job_leaves "${ci_yml}" "${jid}"
done
