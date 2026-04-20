#!/usr/bin/env bash

# Guard against regressions on the Docker-based integration test layer:
# 1. Files under tests/integration/ must not bind to or connect to raw
#    127.0.0.1 / 0.0.0.0 literals. Tests address containers via the
#    fixture's base_url (derived from the ephemeral Docker port mapping)
#    or via in-network service hostnames (e.g. http://agent-auth:9100)
#    that compose interpolates.
# 2. The pytest layer must still build docker/Dockerfile.test so the
#    container actually runs under test. A fixture stack that lost the
#    docker build call would silently skip every integration test.
# 3. Each per-service subdirectory under tests/integration/ must pin
#    its container topology to a tracked artefact so a forgotten compose
#    pin can't fall through to a stale default with no visible error.
#    Acceptable references: the shared docker/docker-compose.yaml file,
#    a per-service docker/compose.test.*.yaml file, or a direct
#    ``docker run`` invocation for one-shot CLI fixtures.

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
  # files (which legitimately construct base_url from the ephemeral
  # Docker port mapping). Helper modules — not just test_*.py — could
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

# The root conftest is responsible for building the test image once per
# session. Either the conftest itself does it inline or it delegates
# to a helper module under tests/integration/. Verify the build path is
# still wired up by checking both candidate locations. Newlines are
# collapsed first so the regex still matches when ruff has split the
# argv list across multiple lines.
build_call_present=0
for candidate in "tests/integration/conftest.py" "tests/integration/_support.py"; do
  [[ -f "${candidate}" ]] || continue
  candidate_flat=$(tr '\n' ' ' <"${candidate}")
  if grep -qE '"docker",\s*"build"' <<<"${candidate_flat}" \
    && grep -qE 'Dockerfile\.test' "${candidate}"; then
    build_call_present=1
    break
  fi
done
if [[ "${build_call_present}" -eq 0 ]]; then
  echo "FAIL: tests/integration/{conftest.py,_support.py} must invoke 'docker build' against docker/Dockerfile.test" >&2
  fail=1
fi

# Each per-service subdirectory must carry a conftest.py that pins its
# container topology to a tracked artefact: the shared
# docker/docker-compose.yaml, a per-service compose.test.*.yaml file,
# or a direct ``docker run`` invocation (one-shot CLI subprocess
# fixtures). A subdir with no conftest at all is rejected outright so a
# new service can't silently fall through to stale defaults. Newlines
# are collapsed so the regex still matches when ruff has split the
# argv list across lines.
shopt -s nullglob
for service_dir in tests/integration/*/; do
  [[ -d "${service_dir}" ]] || continue
  # Skip pytest's bytecode caches and any other dunder directory.
  case "${service_dir}" in
    */__*__/) continue ;;
  esac
  service_conftest="${service_dir}conftest.py"
  if [[ ! -f "${service_conftest}" ]]; then
    echo "FAIL: ${service_dir} must contain a conftest.py pinning container topology" >&2
    fail=1
    continue
  fi
  conftest_flat=$(tr '\n' ' ' <"${service_conftest}")
  if ! grep -qE 'docker-compose\.ya?ml|compose\.test\.[A-Za-z0-9_.-]*ya?ml|"docker",\s*"run"' <<<"${conftest_flat}"; then
    echo "FAIL: ${service_conftest} must reference docker/docker-compose.yaml, a docker/compose.test.*.ya?ml file, or a 'docker run' invocation" >&2
    fail=1
  fi
done
shopt -u nullglob

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi

echo "OK: integration test isolation checks passed"
