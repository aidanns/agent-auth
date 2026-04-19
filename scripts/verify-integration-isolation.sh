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
# 3. Each per-service subdirectory under tests/integration/ must
#    reference a compose.test.*.yaml file so a forgotten compose pin
#    can't fall through to a stale default with no visible error.

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
# still wired up by checking both candidate locations.
build_call_present=0
for candidate in "tests/integration/conftest.py" "tests/integration/_support.py"; do
  if [[ -f "${candidate}" ]] \
    && grep -qE '"docker",[[:space:]]*"build"' "${candidate}" \
    && grep -qE 'Dockerfile\.test' "${candidate}"; then
    build_call_present=1
    break
  fi
done
if [[ "${build_call_present}" -eq 0 ]]; then
  echo "FAIL: tests/integration/{conftest.py,_support.py} must invoke 'docker build' against docker/Dockerfile.test" >&2
  fail=1
fi

# Each per-service subdirectory must reference a compose file in
# docker/. The agent-auth-only fixture lives at the top-level conftest
# and uses compose.test.yaml; service subdirectories use named compose
# files (compose.test.things-bridge.yaml, etc.).
# Per-service conftests must pin their container topology to a tracked
# artefact: either a compose.test.*.yaml file (multi-service stacks) or
# a direct ``docker run`` invocation (one-shot CLI subprocess fixtures).
# Either way, a forgotten reference can't fall through to a stale
# default with no visible error.
for service_conftest in tests/integration/*/conftest.py; do
  [[ -f "${service_conftest}" ]] || continue
  if ! grep -qE 'compose\.test\.[A-Za-z0-9_.-]*ya?ml|"docker",[[:space:]]*"run"' "${service_conftest}"; then
    echo "FAIL: ${service_conftest} must reference a docker/compose.test.*.ya?ml file or a 'docker run' invocation" >&2
    fail=1
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi

echo "OK: integration test isolation checks passed"
