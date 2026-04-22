#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Pure SemVer + Conventional Commits helpers used by scripts/release.sh.
# Sourced — not executed — so it avoids `set` side effects on the caller.

# Walk commits in <range> and emit the largest SemVer bump implied by the
# Conventional Commit subjects/bodies: "major", "minor", "patch", or "none".
#
# Only the four Conventional Commit signals that map to SemVer levels count:
#   - <type>!: subject or BREAKING CHANGE / BREAKING-CHANGE footer → major
#   - feat / feat(scope) subject                                    → minor
#   - fix  / fix(scope)  subject                                    → patch
# Other types (docs, chore, refactor, style, test, ci, build, perf) do not
# produce a release on their own, matching the Conventional Commits spec.
#
# Walks with --first-parent so a merge commit contributes only its own
# subject, not the intermediate commits from the merged branch (matches
# semantic-release / go-semantic-release and keeps the result stable across
# squash- vs merge-commit PR policies).
#
# `revert:` commits: `git revert` copies the reverted commit's full message
# into the body after a 'This reverts commit <sha>.' marker, which would
# otherwise promote a pure revert to a major release when the reverted
# commit had a BREAKING footer. The parser strips everything from that
# marker onward before inspecting the body.
compute_bump() {
  local range="$1"
  local bump="none"
  local log_file record subject body
  # Regexes live in variables because shellcheck can't parse `:` inside `[[ =~ ]]`
  # patterns (SC1073). Quoting the RHS of `=~` would turn it into a literal match,
  # so the variable-indirection trick is the shellcheck-safe way to keep them regex.
  # Conventional Commits requires lowercase types, so match lowercase only and
  # keep the three regexes symmetric.
  local breaking_re='^[a-z]+(\([^)]+\))?!:'
  local feat_re='^feat(\([^)]+\))?:'
  local fix_re='^fix(\([^)]+\))?:'

  # One `git log` call per range (not per commit). A tempfile is used because
  # command substitution cannot hold NUL bytes, and we need `-z` records to
  # handle multi-line bodies cleanly. Capturing via tempfile also lets
  # `set -euo pipefail` actually see git failures — process-substitution
  # errors (`done < <(...)`) are silently swallowed.
  log_file="$(mktemp)"
  # shellcheck disable=SC2094  # Write then read of the same tempfile is sequential, not a pipeline.
  if ! git log --first-parent -z --format='%s%n%b' "${range}" >"${log_file}"; then
    rm -f "${log_file}"
    echo "semver: failed to list commits in range '${range}'" >&2
    return 1
  fi

  # shellcheck disable=SC2094  # Same tempfile as above; we finished writing before reading.
  while IFS= read -r -d '' record; do
    [[ -z "${record}" ]] && continue
    # Split `subject\nbody` at the first newline. For subject-only commits
    # `%s%n%b` still leaves a trailing newline, which both parameter
    # expansions strip correctly (body ends up empty).
    subject="${record%%$'\n'*}"
    body="${record#*$'\n'}"

    # git revert writes "This reverts commit <sha>." into the body followed by
    # the reverted commit's full message. Strip from that marker onward so a
    # revert of a feat!/BREAKING-CHANGE commit doesn't silently promote
    # itself to a major bump.
    body="${body%%This reverts commit *}"

    # <type>!: subject OR BREAKING CHANGE: / BREAKING-CHANGE: footer → major.
    if [[ "${subject}" =~ ${breaking_re} ]] \
      || grep -qE '^BREAKING[ -]CHANGE:' <<<"${body}"; then
      rm -f "${log_file}"
      echo "major"
      return 0
    fi

    if [[ "${subject}" =~ ${feat_re} ]]; then
      [[ "${bump}" != "major" ]] && bump="minor"
      continue
    fi

    if [[ "${subject}" =~ ${fix_re} ]]; then
      [[ "${bump}" == "none" ]] && bump="patch"
      continue
    fi
  done <"${log_file}"

  rm -f "${log_file}"
  echo "${bump}"
}

# Apply a SemVer bump ("major"/"minor"/"patch") to vX.Y.Z and print X.Y.Z.
apply_bump() {
  local last_tag="$1"
  local bump="$2"
  local last_version="${last_tag#v}"
  local major minor patch
  IFS='.' read -r major minor patch <<<"${last_version}"
  case "${bump}" in
    major)
      major=$((major + 1))
      minor=0
      patch=0
      ;;
    minor)
      minor=$((minor + 1))
      patch=0
      ;;
    patch)
      patch=$((patch + 1))
      ;;
    *)
      echo "semver: internal error — unknown bump '${bump}'" >&2
      return 1
      ;;
  esac
  echo "${major}.${minor}.${patch}"
}
