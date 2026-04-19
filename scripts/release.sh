#!/usr/bin/env bash

# Cut a release: validate clean working tree, extract the CHANGELOG entry for
# the requested version, create and push the git tag, then publish the GitHub
# release. Requires CHANGELOG.md to be updated with the version section before
# running. Version string is derived from VCS tags at build time via
# setuptools-scm; this script creates the authoritative tag.
#
# Usage: scripts/release.sh [<version>]
#   scripts/release.sh            # auto-detect from conventional commits since last tag
#   scripts/release.sh 1.2.3      # override with an explicit version
#
# When no version is passed, the next version is computed from the commits
# between the latest v* tag and HEAD using Conventional Commits + SemVer:
#   - any `<type>!:` subject or `BREAKING CHANGE:` footer → major
#   - any `feat:` / `feat(scope):` subject                → minor
#   - any `fix:`  / `fix(scope):`  subject                → patch
#   - other types alone (docs, chore, refactor, ...)      → no release
#
# The resolved version must already appear as a section header in CHANGELOG.md:
#   ## [1.2.3] - YYYY-MM-DD

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ $# -gt 1 ]]; then
  echo "Usage: scripts/release.sh [<version>]" >&2
  echo "  scripts/release.sh            # auto-detect from conventional commits" >&2
  echo "  scripts/release.sh 1.2.3      # override with an explicit version" >&2
  exit 1
fi

for cmd in git gh; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "release: '${cmd}' is required but not found on PATH." >&2
    exit 1
  fi
done

# Walk commits in <range> and emit the largest SemVer bump implied by the
# Conventional Commit subjects/bodies: "major", "minor", "patch", or "none".
# Only the four Conventional Commit types that map to SemVer levels count;
# other types (docs, chore, refactor, style, test, ci, build, perf) do not
# produce a release on their own, matching the Conventional Commits spec.
compute_bump() {
  local range="$1"
  local bump="none"
  local sha subject body
  # Regexes live in variables because shellcheck can't parse `:` inside `[[ =~ ]]`
  # patterns (SC1073). Quoting the RHS of `=~` would turn it into a literal match,
  # so the variable-indirection trick is the shellcheck-safe way to keep them regex.
  local breaking_re='^[a-zA-Z]+(\([^)]+\))?!:'
  local feat_re='^feat(\([^)]+\))?:'
  local fix_re='^fix(\([^)]+\))?:'

  while IFS= read -r sha; do
    [[ -z "${sha}" ]] && continue
    subject="$(git log -1 --format='%s' "${sha}")"
    body="$(git log -1 --format='%b' "${sha}")"

    # `<type>!:` subject OR `BREAKING CHANGE:` / `BREAKING-CHANGE:` footer → major.
    if [[ "${subject}" =~ ${breaking_re} ]] \
      || grep -qE '^BREAKING[ -]CHANGE:' <<<"${body}"; then
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
  done < <(git log --format='%H' "${range}")

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
      echo "release: internal error — unknown bump '${bump}'." >&2
      exit 1
      ;;
  esac
  echo "${major}.${minor}.${patch}"
}

VERSION_AUTO_DETECTED=0
if [[ $# -eq 1 ]]; then
  VERSION="${1}"
else
  VERSION_AUTO_DETECTED=1

  if ! LAST_TAG="$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null)"; then
    echo "release: no 'vX.Y.Z' tag found — the first release needs an explicit version." >&2
    echo "  Run 'scripts/release.sh X.Y.Z' (e.g. 'scripts/release.sh 0.1.0')." >&2
    exit 1
  fi

  # `git describe --match` uses a glob, not a regex, so re-validate the tag
  # format before trusting it for arithmetic.
  if [[ ! "${LAST_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "release: last tag '${LAST_TAG}' is not in vMAJOR.MINOR.PATCH form." >&2
    echo "  Pass an explicit version to override." >&2
    exit 1
  fi

  BUMP="$(compute_bump "${LAST_TAG}..HEAD")"
  if [[ "${BUMP}" == "none" ]]; then
    echo "release: no feat/fix/BREAKING commits since ${LAST_TAG} — nothing to release." >&2
    echo "  Pass an explicit version to override (e.g. 'scripts/release.sh X.Y.Z')." >&2
    exit 1
  fi

  VERSION="$(apply_bump "${LAST_TAG}" "${BUMP}")"
  echo "Auto-detected ${BUMP} bump from commits since ${LAST_TAG}: v${VERSION}"
fi

TAG="v${VERSION}"

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "release: version must be in MAJOR.MINOR.PATCH form (got '${VERSION}')" >&2
  exit 1
fi

if ! git diff --quiet HEAD; then
  echo "release: working tree has uncommitted changes. Commit or stash them first." >&2
  git status --short >&2
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${CURRENT_BRANCH}" != "main" ]]; then
  echo "release: must be run from the 'main' branch (currently on '${CURRENT_BRANCH}')." >&2
  exit 1
fi

# Ensure local main is in sync with remote before tagging.
git fetch origin main --quiet
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
if [[ "${LOCAL_SHA}" != "${REMOTE_SHA}" ]]; then
  echo "release: local main (${LOCAL_SHA:0:7}) differs from origin/main (${REMOTE_SHA:0:7})." >&2
  echo "  Run 'git pull --ff-only' to sync before releasing." >&2
  exit 1
fi

if git rev-parse "${TAG}" >/dev/null 2>&1; then
  echo "release: tag '${TAG}' already exists. Did you mean a different version?" >&2
  exit 1
fi

CHANGELOG="${REPO_ROOT}/CHANGELOG.md"

if [[ ! -f "${CHANGELOG}" ]]; then
  echo "release: CHANGELOG.md not found at repo root." >&2
  exit 1
fi

# Extract the ## [X.Y.Z] section body: collect lines from the header until the
# next ## [ heading (or EOF), then strip leading/trailing blank lines with sed.
# The sed range '/./,/^$/!d' keeps only spans that contain at least one
# non-blank line, which collapses surrounding whitespace without touching body
# content.
changelog_body="$(
  awk "
    /^## \\[${VERSION//./\\.}\\]/ { found=1; next }
    found && /^## \\[/            { exit }
    found                         { print }
  " "${CHANGELOG}" | sed -e '/./,/^$/!d'
)"

if [[ -z "${changelog_body}" ]]; then
  echo "release: no non-empty '## [${VERSION}]' section found in CHANGELOG.md." >&2
  if [[ "${VERSION_AUTO_DETECTED}" -eq 1 ]]; then
    echo "  Rename the '## [Unreleased]' section to '## [${VERSION}] - $(date -u +%F)', " >&2
    echo "  add a fresh empty '## [Unreleased]' above it, commit, push, and re-run." >&2
  else
    echo "  Update CHANGELOG.md with the release notes before running this script." >&2
  fi
  exit 1
fi

echo ""
echo "About to release ${TAG} with the following CHANGELOG entry:"
echo "------------------------------------------------------------------------"
echo "${changelog_body}"
echo "------------------------------------------------------------------------"
echo ""
read -r -p "Proceed? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
  echo "release: aborted." >&2
  exit 1
fi

echo "Creating tag ${TAG} ..."
git tag -s "${TAG}" -m "Release ${TAG}"

echo "Pushing tag ${TAG} to origin ..."
git push origin "${TAG}"

echo "Creating GitHub release ${TAG} ..."
gh release create "${TAG}" \
  --title "${TAG}" \
  --notes "${changelog_body}" \
  --verify-tag

echo ""
echo "Released ${TAG}."
echo "  GitHub: https://github.com/aidanns/agent-auth/releases/tag/${TAG}"
