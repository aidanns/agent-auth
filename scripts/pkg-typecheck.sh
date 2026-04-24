#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Type-check a single workspace package's src/ tree with mypy and
# pyright. Invoked from per-package Taskfiles via
# `task <svc>:typecheck`. scripts/typecheck.sh runs the workspace
# matrix (every packages/*/src + tests/ + benchmarks/) and remains
# the authoritative CI gate; this helper narrows to one package for
# per-service iteration speed.
#
# The mypy / pyright configurations in pyproject.toml and
# pyrightconfig.json set the cross-workspace `mypy_path` / pyright
# `extraPaths` so resolution of `agent-auth-common` imports works
# even when we only feed one package's src tree on the CLI.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/pkg-typecheck.sh <svc>" >&2
  exit 2
fi

svc="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

pkg_dir="packages/${svc}"
if [[ ! -d "${pkg_dir}" ]]; then
  echo "pkg-typecheck: unknown workspace package '${svc}' (no ${pkg_dir}/)" >&2
  exit 2
fi

src_dir="${pkg_dir}/src"
if [[ ! -d "${src_dir}" ]]; then
  echo "pkg-typecheck: ${src_dir}/ does not exist; nothing to check." >&2
  exit 0
fi

uv run --no-sync mypy "${src_dir}"
exec uv run --no-sync pyright "${src_dir}"
