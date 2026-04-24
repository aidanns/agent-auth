#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run a single workspace package's pytest suite (packages/<svc>/tests/).
# Invoked from per-package Taskfiles via `task <svc>:test`. The
# workspace-wide suite is driven by scripts/test.sh — this helper
# stays package-scoped so each service can be iterated on in
# isolation. Extra arguments are forwarded to pytest.
#
# Coverage is disabled here: the workspace-level --cov-fail-under
# floor only makes sense over the full suite (see
# pyproject.toml [tool.pytest.ini_options]). Per-package floors are
# tracked separately in #273.
#
# Until #270 relocates the monolithic tests/ tree into per-package
# trees, packages/<svc>/tests/ does not yet exist. Rather than making
# `task <svc>:test` fail on every package, we report the missing
# directory and exit 0; once #270 lands each package will grow its
# own tree and the helper becomes authoritative.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/pkg-test.sh <svc> [pytest-args...]" >&2
  exit 2
fi

svc="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

pkg_dir="packages/${svc}"
if [[ ! -d "${pkg_dir}" ]]; then
  echo "pkg-test: unknown workspace package '${svc}' (no ${pkg_dir}/)" >&2
  exit 2
fi

tests_dir="${pkg_dir}/tests"
if [[ ! -d "${tests_dir}" ]]; then
  echo "pkg-test: ${tests_dir}/ does not exist; tests have not been relocated yet (tracked in #270)." >&2
  echo "pkg-test: skipping. Run scripts/test.sh to exercise the monolithic suite." >&2
  exit 0
fi

exec uv run --no-sync pytest "${tests_dir}" --no-cov "$@"
