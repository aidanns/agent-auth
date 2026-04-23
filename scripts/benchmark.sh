#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Run the pytest-benchmark suite under benchmarks/ inside the project
# virtualenv. Override the pyproject.toml addopts (which wire
# --cov=src --cov-fail-under=74 for the test suite) so coverage does
# not run against the benchmark tree — benchmarks measure performance
# and exercise only a thin slice of src/, so the unit-test coverage
# floor would always fail.
#
# Arguments after the script name are forwarded to pytest, e.g.
#   scripts/benchmark.sh --benchmark-save=ci-linux-x86_64
#   scripts/benchmark.sh --benchmark-json=benchmarks/results.json
#   scripts/benchmark.sh -k verify_token

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

# ``--override-ini=addopts=`` clears the coverage + fail-under flags
# configured in pyproject.toml [tool.pytest.ini_options]. Columns are
# pinned so the CI log is stable and readable across runs.
exec uv run --no-sync pytest \
  --override-ini="addopts=" \
  --benchmark-columns=min,mean,median,stddev,ops,rounds \
  --benchmark-sort=mean \
  --benchmark-storage=benchmarks/baselines \
  benchmarks/ \
  "$@"
