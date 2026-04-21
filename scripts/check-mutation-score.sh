#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Read the mutation-score stats written by `mutmut export-cicd-stats`
# and fail if the score (killed / (killed + survived)) drops below the
# floor declared in pyproject.toml's [tool.mutation_score] fail_under.
#
# Intended to run after scripts/mutation-test.sh in the mutation CI
# workflow. Exits 0 if the score is above the floor, 1 otherwise. The
# floor is ratcheted upward per CONTRIBUTING.md § "Mutation score".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

STATS_FILE="mutants/mutmut-cicd-stats.json"
if [[ ! -f "${STATS_FILE}" ]]; then
  echo "check-mutation-score: ${STATS_FILE} missing — run scripts/mutation-test.sh first." >&2
  exit 1
fi

python3 - "${STATS_FILE}" <<'PY'
import json
import pathlib
import sys
import tomllib

stats_path = pathlib.Path(sys.argv[1])
stats = json.loads(stats_path.read_text())

pyproject = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
try:
    fail_under = float(pyproject["tool"]["mutation_score"]["fail_under"])
except KeyError:
    print(
        "check-mutation-score: pyproject.toml is missing [tool.mutation_score] fail_under.",
        file=sys.stderr,
    )
    sys.exit(1)

killed = int(stats.get("killed", 0))
survived = int(stats.get("survived", 0))
total_actionable = killed + survived

if total_actionable == 0:
    print(
        "check-mutation-score: no actionable mutants (killed+survived=0).",
        "Treating this as a configuration problem — mutmut produced no mutants to evaluate.",
        file=sys.stderr,
    )
    sys.exit(1)

score = 100.0 * killed / total_actionable
print(
    f"check-mutation-score: mutation score = {score:.2f}% "
    f"(killed={killed}, survived={survived}, fail_under={fail_under:.2f}%)"
)
for extra_key in ("no_tests", "skipped", "suspicious", "timeout", "segfault"):
    value = stats.get(extra_key, 0)
    if value:
        print(f"  {extra_key}: {value}")

if score < fail_under:
    print(
        f"check-mutation-score: score {score:.2f}% is below fail_under "
        f"{fail_under:.2f}% — raise coverage on survivors or reduce the floor "
        f"(but note CONTRIBUTING.md § 'Mutation score' forbids lowering it).",
        file=sys.stderr,
    )
    sys.exit(1)
PY
