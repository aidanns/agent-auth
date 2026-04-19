#!/usr/bin/env bash

# Cut a release: validate clean working tree, extract the CHANGELOG entry for
# the requested version, create and push the git tag, then publish the GitHub
# release. Requires CHANGELOG.md to be updated with the version section before
# running. Version string is derived from VCS tags at build time via
# setuptools-scm; this script creates the authoritative tag.
#
# Usage: scripts/release.sh [-y|--yes] [<version>]
#   scripts/release.sh            # auto-detect from conventional commits since last tag
#   scripts/release.sh 1.2.3      # override with an explicit version
#   scripts/release.sh -y         # skip the "Proceed?" confirmation prompt
#
# When no version is passed, the next version is computed from the commits
# between the latest v* tag and HEAD using Conventional Commits + SemVer:
#   - any `<type>!:` subject or `BREAKING CHANGE:` footer → major
#   - any `feat:` / `feat(scope):` subject                → minor
#   - any `fix:`  / `fix(scope):`  subject                → patch
#   - other types alone (docs, chore, refactor, ...)      → no release
#
# Pre-v1.0.0 exception: while the current tag is in the 0.x range the API is
# not considered stable (SemVer 2.0.0 §4), so a detected major bump is
# demoted to a minor bump. Pass an explicit '1.0.0' to graduate.
#
# The resolved version must already appear as a section header in CHANGELOG.md:
#   ## [1.2.3] - YYYY-MM-DD

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=lib/semver.sh
source "${SCRIPT_DIR}/lib/semver.sh"

cd "${REPO_ROOT}"

usage() {
  cat <<'EOF' >&2
Usage: scripts/release.sh [-y|--yes] [<version>]
  scripts/release.sh            # auto-detect from conventional commits
  scripts/release.sh 1.2.3      # override with an explicit version
  scripts/release.sh -y         # skip the "Proceed?" confirmation prompt
EOF
}

ASSUME_YES=0
while [[ $# -gt 0 ]]; do
  case "${1}" in
    -y | --yes)
      ASSUME_YES=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "release: unknown flag '${1}'" >&2
      usage
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -gt 1 ]]; then
  usage
  exit 1
fi

for cmd in git gh; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "release: '${cmd}' is required but not found on PATH." >&2
    exit 1
  fi
done

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

  # Pre-v1.0.0 API: the public surface is not considered stable until the
  # v1.0.0 graduation release, so BREAKING commits bump the minor number
  # rather than the major number. SemVer 2.0.0 §4 explicitly permits this.
  DEMOTED_FROM=""
  if [[ "${BUMP}" == "major" && "${LAST_TAG}" =~ ^v0\. ]]; then
    DEMOTED_FROM="major"
    BUMP="minor"
  fi

  VERSION="$(apply_bump "${LAST_TAG}" "${BUMP}")"
  if [[ -n "${DEMOTED_FROM}" ]]; then
    echo "Auto-detected ${DEMOTED_FROM} bump from commits since ${LAST_TAG}; demoted to ${BUMP} per pre-v1.0.0 API rule: v${VERSION}"
  else
    echo "Auto-detected ${BUMP} bump from commits since ${LAST_TAG}: v${VERSION}"
  fi
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
if [[ "${ASSUME_YES}" -eq 1 ]]; then
  echo "--yes supplied; skipping confirmation."
else
  read -r -p "Proceed? [y/N] " confirm
  if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "release: aborted." >&2
    exit 1
  fi
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
