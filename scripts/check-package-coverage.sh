#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# After a workspace pytest run that produced a unified ``.coverage``
# database, enforce each package's ``--cov-fail-under`` floor against
# its slice of the report. Fails the gate as soon as any package
# regresses, listing every offending package (not just the first).
#
# Per-package floors live in each ``packages/<svc>/pyproject.toml``
# under ``[tool.pytest.ini_options].addopts`` as
# ``--cov-fail-under=N``. Per-package coverage selectors live in the
# same addopts as ``--cov=<top-level-module>`` entries; this helper
# uses those modules to scope ``coverage report --include`` to the
# package's source tree.
#
# Tracked by issue #273 (per-package coverage floors).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_bootstrap_venv.sh
source "${SCRIPT_DIR}/_bootstrap_venv.sh"

if [[ ! -f .coverage ]]; then
  echo "check-package-coverage: no .coverage database found in $(pwd)." >&2
  echo "  Run 'task test' (or 'scripts/test.sh --unit') first." >&2
  exit 2
fi

fail=0
for pkg_dir in packages/*/; do
  pkg_name="$(basename "${pkg_dir}")"
  pyproject="${pkg_dir}pyproject.toml"
  [[ -f "${pyproject}" ]] || continue

  meta="$(
    uv run --no-sync python3 - "${pyproject}" "${pkg_dir}" <<'PY'
import sys
import tomllib
from pathlib import Path

pyproject_path, pkg_dir = sys.argv[1:3]
with open(pyproject_path, "rb") as f:
    cfg = tomllib.load(f)
addopts = cfg.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts", [])
if isinstance(addopts, str):
    addopts = addopts.split()
floor = ""
modules: list[str] = []
i = 0
while i < len(addopts):
    arg = addopts[i]
    if arg.startswith("--cov-fail-under="):
        floor = arg.split("=", 1)[1]
    elif arg == "--cov-fail-under" and i + 1 < len(addopts):
        floor = addopts[i + 1]
        i += 1
    elif arg.startswith("--cov="):
        modules.append(arg.split("=", 1)[1])
    elif arg == "--cov" and i + 1 < len(addopts):
        modules.append(addopts[i + 1])
        i += 1
    i += 1

# Translate ``--cov=<module>`` entries to file globs under the
# package's src/ tree so ``coverage report --include`` matches the
# right files. Skip a package that defines no coverage selectors —
# it's a library member with no own tests (very rare).
include_globs: list[str] = []
src_dir = Path(pkg_dir) / "src"
for module in modules:
    module_path = src_dir / module
    if module_path.is_dir():
        include_globs.append(f"{module_path}/*")
print(floor or "")
print(",".join(include_globs))
PY
  )"
  floor="$(awk 'NR==1' <<<"${meta}")"
  cov_paths="$(awk 'NR==2' <<<"${meta}")"

  if [[ -z "${floor}" ]]; then
    echo "check-package-coverage: ${pkg_name} has no --cov-fail-under in pyproject.toml." >&2
    fail=1
    continue
  fi
  if [[ -z "${cov_paths}" ]]; then
    echo "check-package-coverage: ${pkg_name} has no resolvable --cov modules in pyproject.toml." >&2
    fail=1
    continue
  fi

  # ``coverage report --fail-under=N --include=<glob1,glob2>`` exits
  # 2 when the slice falls below the floor. Pass all include globs
  # as a single comma-separated list (coverage.py treats multiple
  # ``--include=`` flags as an AND not OR; the comma form is the
  # documented union).
  if ! report_output=$(
    uv run --no-sync coverage report \
      --fail-under="${floor}" \
      --include="${cov_paths}" 2>&1
  ); then
    echo "check-package-coverage: ${pkg_name} below floor ${floor}%:" >&2
    printf '  %s\n' "${report_output//$'\n'/$'\n'  }" >&2
    fail=1
  else
    pct=$(grep -E "^TOTAL " <<<"${report_output}" | awk '{print $NF}')
    echo "check-package-coverage: ${pkg_name} ${pct} (floor ${floor}%)"
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
