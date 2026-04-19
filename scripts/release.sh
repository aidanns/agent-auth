#!/usr/bin/env bash

# Cut a release: validate clean working tree, extract the CHANGELOG entry for
# the requested version, create and push the git tag, then publish the GitHub
# release. Requires CHANGELOG.md to be updated with the version section before
# running. Version string is derived from VCS tags at build time via
# setuptools-scm; this script creates the authoritative tag.
#
# Usage: scripts/release.sh <version>
#   e.g. scripts/release.sh 1.2.3
#
# The version must already appear as a section header in CHANGELOG.md:
#   ## [1.2.3] - YYYY-MM-DD

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/release.sh <version>" >&2
  echo "  e.g. scripts/release.sh 1.2.3" >&2
  exit 1
fi

VERSION="${1}"
TAG="v${VERSION}"

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "release: version must be in MAJOR.MINOR.PATCH form (got '${VERSION}')" >&2
  exit 1
fi

for cmd in git gh; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "release: '${cmd}' is required but not found on PATH." >&2
    exit 1
  fi
done

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
  echo "  Update CHANGELOG.md with the release notes before running this script." >&2
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
