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
# Each ``packages/<svc>/pyproject.toml`` carries its own
# ``[tool.pytest.ini_options]`` with ``--cov=src`` and
# ``--cov-fail-under=N`` (the per-package floor set in #273). Pytest's
# rootdir discovery resolves to ``packages/<svc>/`` when the test
# path is under that tree, so those settings load automatically.
# Integration trees under ``packages/<svc>/tests/integration/`` are
# excluded — they belong to the Docker-backed run driven by
# scripts/test.sh.

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
  echo "pkg-test: ${tests_dir}/ does not exist." >&2
  echo "pkg-test: skipping. Run scripts/test.sh to exercise the workspace suite." >&2
  exit 0
fi

# Ignore the per-package integration/ subdir if present — those tests
# need Docker and the workspace-level scripts/test.sh --integration
# fixtures, not the in-process unit-test ratchet driven by this script.
ignore_args=()
if [[ -d "${tests_dir}/integration" ]]; then
  ignore_args+=("--ignore=${tests_dir}/integration")
fi

exec uv run --no-sync pytest "${tests_dir}" "${ignore_args[@]}" "$@"
