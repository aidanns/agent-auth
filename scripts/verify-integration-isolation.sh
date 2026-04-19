#!/usr/bin/env bash

# Guard against regressions on the Docker-based integration test layer:
# 1. Files under tests/integration/ must not bind to or connect to raw
#    127.0.0.1 literals. Tests address the container via
#    ``agent_auth_container.base_url`` which the fixture derives from the
#    ephemeral Docker port mapping.
# 2. The pytest fixture must still build docker/Dockerfile.test so the
#    container actually runs under test. A conftest that lost the
#    ``docker build`` call would silently skip every integration test.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

fail=0

integration_dir="tests/integration"
if [[ ! -d "${integration_dir}" ]]; then
  echo "FAIL: ${integration_dir}/ is missing" >&2
  fail=1
else
  # Scan every Python file under tests/integration/ except conftest.py
  # (which legitimately constructs base_url from the ephemeral Docker
  # port mapping). Helper modules — not just ``test_*.py`` — could
  # otherwise smuggle a raw loopback literal back into the black-box
  # boundary.
  offenders=$(grep -nR --include='*.py' --exclude='conftest.py' \
    -E '127\.0\.0\.1|0\.0\.0\.0' "${integration_dir}" || true)
  if [[ -n "${offenders}" ]]; then
    echo "FAIL: integration test files must not reference 127.0.0.1 / 0.0.0.0 directly:" >&2
    echo "${offenders}" >&2
    fail=1
  fi
fi

conftest="tests/integration/conftest.py"
if ! grep -qE '"docker",\s*"build"' "${conftest}" \
  || ! grep -qE 'Dockerfile\.test' "${conftest}"; then
  echo "FAIL: ${conftest} must invoke 'docker build' against docker/Dockerfile.test" >&2
  fail=1
fi

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi

echo "OK: integration test isolation checks passed"
