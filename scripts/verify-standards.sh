#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify generic, portable project standards mandated by
# .claude/instructions/. This script intentionally does NOT assert on
# anything project-specific (service names, repo-specific CLI entry
# points, domain tasks) — those belong in project documentation, not in
# the standards gate. REQUIRED_TASKS only lists the task names the
# cross-project tooling standard mandates (build, lint, format, test,
# ...); project-specific tasks like running a local service CLI are
# added to Taskfile.yml without being required here.
#
# Checks grow over time as new cross-cutting standards are added. Today:
#
#   1. Taskfile.yml exposes every generic task named in REQUIRED_TASKS
#      (see tooling-and-ci.md Orchestration).
#   2. .github/dependabot.yml covers every dependency ecosystem actually
#      in use by this repository with minor/patch grouping (see
#      tooling-and-ci.md Security). An ecosystem is "in use" when its
#      manifest files are present; ecosystems without manifests are
#      skipped rather than required.
#   2a. Third-party GitHub Actions enumerated in PINNED_ACTIONS use the
#      sha+trailing-comment pin form (see issue #83 and the OpenSSF
#      Scorecard `pinned-dependencies` check).
#   2b. Every astral-sh/setup-uv invocation passes an explicit
#      `with.version` so the uv binary can't silently upgrade between
#      runs (see issue #84).
#   3. Bash gating (shellcheck, shfmt) is wired into CI, treefmt, and
#      lefthook per .claude/instructions/bash.md.
#   4. Markdown (mdformat) and TOML (taplo) formatters are wired into
#      treefmt.toml, and keep-sorted is wired into either lefthook.yml
#      pre-commit or a CI workflow, per
#      .claude/instructions/tooling-and-ci.md.
#   5. uv is the sole Python resolver per .claude/instructions/python.md:
#      uv.lock matches pyproject.toml, and no scripts/*.sh file invokes
#      `pip install` to bootstrap a venv.
#   6. ruff is configured in pyproject.toml, wired into treefmt and
#      lefthook, and gated in CI per .claude/instructions/python.md.
#   7. CONTRIBUTING.md exists at repo root and contains dev-setup, testing,
#      release, and commit-signing sections per
#      .claude/instructions/release-and-hygiene.md.
#   8. Every file under design/decisions/ (other than README.md and
#      TEMPLATE.md) contains Context / Decision / Consequences sections
#      and is linked from design/decisions/README.md, per
#      .claude/instructions/design.md "Architecture Decision Records".
#   9. design/ASSURANCE.md exists, declares a QM or SIL level, and lists
#      the required activities and evidence for that level, per
#      .claude/instructions/design.md "Quality management / safety
#      integrity level".
#  10. lefthook pre-commit hook is installed in the local clone when
#      lefthook.yml is present (skipped under CI=true, since CI enforces
#      the same gates via explicit workflow steps).
#  11. .github/workflows/verify-function-tests.yml (if present) does NOT
#      mark the verify step continue-on-error, so regressions in
#      function-to-test allocation fail CI.
#  12. A mutation-testing tool is configured (e.g. [tool.mutmut] in
#      pyproject.toml) and a scheduled CI workflow invokes it with a
#      documented score threshold, per
#      .claude/instructions/testing-standards.md "Mutation testing on
#      security-critical paths".
#  13. A tests/fault/ directory exists and contains test files covering
#      each listed fault-injection scenario (SQLite write errors,
#      audit-log disk-full, keyring unavailable, notification plugin
#      timeout/exception, agent-auth unreachable, Things AppleScript
#      failures), per .claude/instructions/testing-standards.md
#      "Chaos and fault-injection tests".
#  14. design/DESIGN.md documents a latency budget for critical
#      operations AND at least one test carries the perf_budget
#      pytest marker, per .claude/instructions/testing-standards.md
#      "Performance budget".
#  15. A benchmarks/ directory contains at least one test_*.py file
#      AND a scheduled CI workflow (.github/workflows/benchmark.yml)
#      invokes it on `on: schedule:`, per
#      .claude/instructions/testing-standards.md "Benchmark suite".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v task >/dev/null 2>&1; then
  echo "verify-standards: 'task' (go-task) is not on PATH." >&2
  echo "Install it from https://taskfile.dev/installation/ and re-run." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "verify-standards: 'python3' is required to parse the task catalogue." >&2
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "verify-standards: 'yq' (https://github.com/mikefarah/yq) is required to parse the dependabot config." >&2
  exit 1
fi

# Only list task names that are required by the cross-project tooling
# standard, not project-specific service/CLI entry points. See the
# header comment for the rationale.
REQUIRED_TASKS=(
  # keep-sorted start
  build
  check
  format
  install-hooks
  lint
  release
  test
  verify-dependencies
  verify-design
  verify-function-tests
  verify-standards
  # keep-sorted end
)

catalogue="$(task --list-all --json)"

# Capture into a variable (not process substitution) so `set -e` catches a
# crash in the python helper — otherwise a parser failure silently yields an
# empty `missing` array and the check falsely reports success.
missing_output="$(
  python3 - "${catalogue}" "${REQUIRED_TASKS[@]}" <<'PY'
import json
import sys

catalogue = json.loads(sys.argv[1])
required = set(sys.argv[2:])
present = {task["name"] for task in catalogue.get("tasks", [])}
for name in sorted(required - present):
    print(name)
PY
)"

if [[ -n "${missing_output}" ]]; then
  mapfile -t missing <<<"${missing_output}"
  echo "verify-standards: Taskfile.yml is missing required tasks:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

echo "verify-standards: Taskfile.yml exposes all required tasks."

DEPENDABOT_CONFIG="${REPO_ROOT}/.github/dependabot.yml"

if [[ ! -f "${DEPENDABOT_CONFIG}" ]]; then
  echo "verify-standards: ${DEPENDABOT_CONFIG} is missing" >&2
  exit 1
fi

required_ecosystems=()

if [[ -f pyproject.toml ]] || [[ -f setup.py ]] || compgen -G 'requirements*.txt' >/dev/null; then
  required_ecosystems+=(pip)
fi

if compgen -G '.github/workflows/*.yml' >/dev/null || compgen -G '.github/workflows/*.yaml' >/dev/null; then
  required_ecosystems+=(github-actions)
fi

if [[ -f package.json ]]; then
  required_ecosystems+=(npm)
fi

if [[ ${#required_ecosystems[@]} -eq 0 ]]; then
  echo "verify-standards: no known dependency ecosystems detected; skipping dependabot coverage check."
else
  for ecosystem in "${required_ecosystems[@]}"; do
    matched=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .[\"package-ecosystem\"]" "${DEPENDABOT_CONFIG}")
    if [[ "${matched}" != "${ecosystem}" ]]; then
      echo "verify-standards: dependabot.yml does not declare the '${ecosystem}' ecosystem" >&2
      exit 1
    fi

    update_types=$(yq ".updates[] | select(.[\"package-ecosystem\"] == \"${ecosystem}\") | .groups.[].update-types[]" "${DEPENDABOT_CONFIG}")
    for update_type in minor patch; do
      if ! printf '%s\n' "${update_types}" | grep -qFx "${update_type}"; then
        echo "verify-standards: ecosystem '${ecosystem}' does not group '${update_type}' updates" >&2
        exit 1
      fi
    done
  done

  echo "verify-standards: dependabot.yml covers detected ecosystems (${required_ecosystems[*]}) with minor/patch grouping."
fi

# ---------------------------------------------------------------------------
# Third-party actions are sha-pinned with a trailing ` # <tag>` comment.
# ---------------------------------------------------------------------------
# A bare `uses: owner/action@v6` satisfies no supply-chain control: the
# tag can be force-moved upstream without touching this repo. The
# project standard is `uses: owner/action@<sha> # v6` — the sha locks
# the ref and the trailing comment documents the human-readable version
# that Dependabot / Renovate bump together.
#
# PINNED_ACTIONS lists the third-party action prefixes that must be
# sha-pinned. Add new actions here as follow-up PRs convert them to the
# pinned form (see issue #83). Entries match against the full
# `uses: <owner>/<action>` path — trailing slashes are stripped before
# comparison so `github/codeql-action` can be added to catch any of its
# sub-actions (analyze, init, upload-sarif).
PINNED_ACTIONS=(
  # keep-sorted start
  actions/checkout
  astral-sh/setup-uv
  # keep-sorted end
)

pinned_drift=0
for wf in .github/workflows/*.yml .github/actions/*/action.yml; do
  [[ -f "${wf}" ]] || continue
  while IFS= read -r line; do
    # Capture the `uses: owner/name[/sub]@ref[ # tag]` tail after stripping
    # leading whitespace and the optional `- ` list marker. Lines without
    # `uses:` are already excluded by the grep filter below.
    stripped="${line#"${line%%[![:space:]]*}"}" # ltrim
    stripped="${stripped#- }"
    stripped="${stripped#uses:}"
    stripped="${stripped#"${stripped%%[![:space:]]*}"}" # ltrim again
    # stripped is now e.g. "actions/checkout@v6" or
    # "actions/checkout@<sha> # v6".
    action_path="${stripped%@*}"
    ref_and_comment="${stripped#*@}"
    for pinned in "${PINNED_ACTIONS[@]}"; do
      # Match on exact repo path or a `/`-prefixed sub-action (so
      # "github/codeql-action" covers "github/codeql-action/analyze").
      if [[ "${action_path}" == "${pinned}" ]] \
        || [[ "${action_path}" == "${pinned}/"* ]]; then
        if [[ ! "${ref_and_comment}" =~ ^[0-9a-f]{40}[[:space:]]+#[[:space:]]+.+$ ]]; then
          echo "verify-standards: ${wf} has '${pinned}' reference not in sha+comment form: ${stripped}" >&2
          pinned_drift=1
        fi
        break
      fi
    done
  done < <(grep -nE "^\s*-?\s*uses:\s" "${wf}" | cut -d: -f2-)
done

if [[ ${pinned_drift} -ne 0 ]]; then
  echo "  Expected: uses: <owner>/<action>@<40-char-sha> # <tag>" >&2
  echo "  Rationale: a bare tag can be force-moved upstream without changing this repo. See issue #83." >&2
  exit 1
fi

echo "verify-standards: third-party actions in PINNED_ACTIONS (${PINNED_ACTIONS[*]}) use sha+comment form."

# ---------------------------------------------------------------------------
# Every astral-sh/setup-uv invocation pins the uv binary version.
# ---------------------------------------------------------------------------
# Without an explicit `version:` input, setup-uv installs whatever
# `uv-version` or `latest` resolves to at run time — drift we don't
# want on a security-signing toolchain. The setup-toolchain composite
# action exposes `uv-version` as a top-level input whose default feeds
# `with.version`; direct workflow invocations hardcode the literal
# until the central tool-versions manifest from #87 is available.
uv_version_drift=0
uv_version_matches=0
for wf in .github/workflows/*.yml .github/actions/*/action.yml; do
  [[ -f "${wf}" ]] || continue
  # yq emits one document per `uses: astral-sh/setup-uv@...` step with
  # its `with` block; absence of a `.with.version` key (or an empty
  # string) is the drift signal.
  while IFS=$'\t' read -r step_wf version_value; do
    [[ -n "${step_wf}" ]] || continue
    uv_version_matches=$((uv_version_matches + 1))
    if [[ -z "${version_value}" || "${version_value}" == "null" ]]; then
      echo "verify-standards: ${wf} invokes astral-sh/setup-uv without 'with.version' set." >&2
      uv_version_drift=1
    fi
  done < <(
    WF="${wf}" yq eval -o=tsv '
      [.. | select(type == "!!map" and has("uses") and (.uses | test("^astral-sh/setup-uv@")))
        | [(env(WF) // "wf"), (.with.version // "")]
      ] | .[] | @tsv
    ' "${wf}" 2>/dev/null
  )
done

if [[ ${uv_version_drift} -ne 0 ]]; then
  echo "  Expected: with.version: \"<pin>\" (or \${{ inputs.uv-version }} inside the composite action)." >&2
  echo "  Rationale: pin the uv binary so CI can't silently upgrade. See issue #84." >&2
  exit 1
fi

if [[ ${uv_version_matches} -eq 0 ]]; then
  echo "verify-standards: no astral-sh/setup-uv invocations found — skipping uv-version pin check." >&2
else
  echo "verify-standards: all ${uv_version_matches} astral-sh/setup-uv invocations pin 'with.version'."
fi

# Bash tooling: shellcheck + shfmt must be wired into CI, treefmt, and
# lefthook per .claude/instructions/bash.md. Strip comments before
# grepping so a stale `# shellcheck` mention doesn't satisfy the check
# after the actual invocation has been removed.

bash_tool_missing=0

fail_bash_check() {
  echo "verify-standards: '$1' is not wired into $2." >&2
  echo "  $3" >&2
  bash_tool_missing=1
}

strip_comments() {
  sed -E 's/(^|[[:space:]])#.*$//' "$@"
}

# Collect comment-stripped content into variables so the match step
# doesn't early-exit its upstream pipeline — `grep -q` exiting on first
# match would otherwise SIGPIPE `sed`/`cat`, and `pipefail` turns that
# into a whole-pipeline failure when the input is large enough to race.
workflows_stripped="$(find .github/workflows .github/actions -name '*.yml' -print0 2>/dev/null \
  | xargs -0 -r cat 2>/dev/null \
  | strip_comments)"
# Narrower scan: only CI workflow files, excluding composite-action
# definitions under .github/actions/. Lets checks distinguish "tool
# invoked by CI" from "tool installed by a setup action" — a tool that
# only appears in an install step is not actually gated.
workflows_only_stripped="$(find .github/workflows -name '*.yml' -print0 2>/dev/null \
  | xargs -0 -r cat 2>/dev/null \
  | strip_comments)"
treefmt_stripped=""
[[ -f treefmt.toml ]] && treefmt_stripped="$(strip_comments treefmt.toml)"
lefthook_stripped=""
[[ -f lefthook.yml ]] && lefthook_stripped="$(strip_comments lefthook.yml)"
scripts_stripped="$(find scripts -name '*.sh' -print0 2>/dev/null \
  | xargs -0 -r cat 2>/dev/null \
  | strip_comments)"

for tool in shellcheck shfmt; do
  if ! grep -qE "\\b${tool}\\b" <<<"${workflows_stripped}"; then
    fail_bash_check "${tool}" ".github/workflows/*.yml" \
      "Add a workflow step that invokes '${tool}' (see .github/workflows/check.yml)."
  fi

  if ! grep -qE "^\\[formatter\\.${tool}\\]" <<<"${treefmt_stripped}"; then
    fail_bash_check "${tool}" "treefmt.toml" \
      "Add a [formatter.${tool}] entry to treefmt.toml."
  fi

  # lefthook is satisfied either by a direct invocation of the tool or by
  # invoking treefmt — treefmt runs the tool transitively via its
  # [formatter.${tool}] entry (asserted above).
  if ! grep -qE "\\b${tool}\\b" <<<"${lefthook_stripped}" \
    && ! grep -qE "\\btreefmt\\b" <<<"${lefthook_stripped}"; then
    fail_bash_check "${tool}" "lefthook.yml" \
      "Add a pre-commit command that invokes '${tool}' (or 'treefmt') to lefthook.yml."
  fi
done

if [[ ${bash_tool_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: shellcheck and shfmt are wired into CI, treefmt, and lefthook."

# mdformat, taplo, and keep-sorted gating per
# .claude/instructions/tooling-and-ci.md. keep-sorted may be wired via
# either lefthook.yml or a CI workflow.

doc_tool_missing=0

fail_doc_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  doc_tool_missing=1
}

for tool in mdformat taplo; do
  if ! grep -qE "^\\[formatter\\.${tool}\\]" <<<"${treefmt_stripped}"; then
    fail_doc_check "'${tool}' is not registered as a treefmt formatter in treefmt.toml." \
      "Add a [formatter.${tool}] section to treefmt.toml."
  fi
done

# Match the invocation pattern `keep-sorted --mode=...` rather than the bare
# tool name — a CI workflow's install step mentions `keep-sorted` without
# actually running it, which would otherwise defeat the regression check.
# Covers lefthook.yml pre-commit, workflow YAML, and scripts/*.sh (since CI
# runs scripts/lint.sh transitively via `task check`).
if ! grep -qE "keep-sorted --mode=" <<<"${lefthook_stripped}" \
  && ! grep -qE "keep-sorted --mode=" <<<"${workflows_stripped}" \
  && ! grep -qE "keep-sorted --mode=" <<<"${scripts_stripped}"; then
  fail_doc_check "'keep-sorted' is not invoked in lefthook.yml, any .github/workflows/*.yml, or scripts/*.sh." \
    "Add a 'keep-sorted --mode=lint' invocation to one of those locations."
fi

if [[ ${doc_tool_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: mdformat + taplo are wired into treefmt, and keep-sorted is configured."

# treefmt + lefthook + ripsecrets standard per
# .claude/instructions/tooling-and-ci.md (Orchestration, Security) and
# the deterministic regression check in issue #42:
#
#   - treefmt.toml exists at the repo root.
#   - lefthook.yml exists at the repo root.
#   - lefthook.yml pre-commit stage invokes 'ripsecrets' and 'treefmt'.
#   - At least one CI workflow runs 'treefmt --ci' (or equivalent
#     check-mode invocation: --no-cache + --fail-on-change).
#   - At least one CI workflow runs 'ripsecrets'.

orchestration_missing=0

fail_orchestration_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  orchestration_missing=1
}

if [[ ! -f treefmt.toml ]]; then
  fail_orchestration_check \
    "treefmt.toml is missing from the repo root." \
    "Create treefmt.toml registering every formatter (see .claude/instructions/tooling-and-ci.md)."
fi

if [[ ! -f lefthook.yml ]]; then
  fail_orchestration_check \
    "lefthook.yml is missing from the repo root." \
    "Create lefthook.yml with pre-commit commands that run ripsecrets and treefmt."
else
  if ! grep -qE "\\bripsecrets\\b" <<<"${lefthook_stripped}"; then
    fail_orchestration_check \
      "lefthook.yml does not invoke 'ripsecrets' on pre-commit." \
      "Add a pre-commit command that runs 'ripsecrets {staged_files}'."
  fi

  if ! grep -qE "\\btreefmt\\b" <<<"${lefthook_stripped}"; then
    fail_orchestration_check \
      "lefthook.yml does not invoke 'treefmt' on pre-commit." \
      "Add a pre-commit command that runs 'treefmt --no-cache --fail-on-change {staged_files}'."
  fi
fi

# Accept either the explicit '--ci' shorthand or the equivalent expansion
# ('--no-cache' AND '--fail-on-change') on a workflow `run:` line — both
# run treefmt in write-suppressed check mode. Scoped to
# workflows_only_stripped and prefixed with `run:` so the install step
# in .github/actions/setup-toolchain/action.yml (which shells
# `ripsecrets --version` / `treefmt --version` for smoke checks) can't
# satisfy the gate.
if ! grep -qE "run:[[:space:]]*treefmt[^\\n]*--ci" <<<"${workflows_only_stripped}" \
  && ! grep -qE "run:[[:space:]]*treefmt[^\\n]*--no-cache[^\\n]*--fail-on-change" <<<"${workflows_only_stripped}"; then
  fail_orchestration_check \
    "no .github/workflows/*.yml runs 'treefmt --ci' (or '--no-cache --fail-on-change')." \
    "Add a workflow step that runs 'treefmt --ci' (see .github/workflows/check.yml)."
fi

# Match `run: ripsecrets` (single-line) to distinguish a real CI
# invocation from a setup-action install step's `ripsecrets --version`
# smoke test. Scoped to workflows_only_stripped for the same reason.
if ! grep -qE "run:[[:space:]]*ripsecrets([[:space:]]|$)" <<<"${workflows_only_stripped}"; then
  fail_orchestration_check \
    "no .github/workflows/*.yml invokes 'ripsecrets' as a CI step." \
    "Add a workflow step that runs 'ripsecrets' against the tree (see .github/workflows/check.yml)."
fi

if [[ ${orchestration_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: treefmt.toml + lefthook.yml exist, lefthook runs ripsecrets + treefmt, and CI runs treefmt --ci + ripsecrets."

# uv is the project-standard Python resolver (.claude/instructions/python.md).
# Two invariants:
#   1. uv.lock is in sync with pyproject.toml (`uv lock --check`).
#   2. No scripts/*.sh file reintroduces `pip install` for venv bootstrap.

if [[ -f pyproject.toml ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "verify-standards: 'uv' is required to verify uv.lock is in sync." >&2
    echo "  Install from https://astral.sh/uv/install.sh and re-run." >&2
    exit 1
  fi

  # `uv lock --check` exits non-zero for both a missing lockfile and a
  # stale one, so a single call covers both invariants.
  if ! uv lock --check >/dev/null 2>&1; then
    echo "verify-standards: uv.lock is missing or out of date with pyproject.toml." >&2
    echo "  Run 'uv lock' and commit the result." >&2
    exit 1
  fi

  echo "verify-standards: uv.lock is in sync with pyproject.toml."
fi

# Ban `pip install` in scripts/. Collapse backslash-newline continuations
# first so `pip \` / `install` on separate lines still trips the check,
# then strip comments so a docstring-style reference in a heredoc doesn't
# trigger a false positive. This script is excluded from the scan
# because it references the forbidden pattern in its own diagnostic
# output.
pip_install_offenders=()
while IFS= read -r script; do
  [[ -f "${script}" ]] || continue
  [[ "${script}" == "scripts/verify-standards.sh" ]] && continue
  if sed ':a;N;$!ba;s/\\\n/ /g' "${script}" | strip_comments | grep -qE '\bpip[0-9]*\b[^\n]*\binstall\b'; then
    pip_install_offenders+=("${script}")
  fi
done < <(find scripts -type f -name '*.sh' -print)

if [[ ${#pip_install_offenders[@]} -gt 0 ]]; then
  echo "verify-standards: scripts/ must not invoke 'pip install' (use 'uv sync')." >&2
  printf '  - %s\n' "${pip_install_offenders[@]}" >&2
  exit 1
fi

echo "verify-standards: no scripts/*.sh file invokes 'pip install'."

# Python tooling: ruff must be configured in pyproject.toml, wired into
# treefmt, and gated in CI per .claude/instructions/python.md. The CI
# gate is satisfied transitively by `task check`, which dispatches to
# scripts/lint.sh and scripts/format.sh (both now invoke ruff).

ruff_missing=0

fail_ruff_check() {
  echo "verify-standards: ruff is not wired into $1." >&2
  echo "  $2" >&2
  ruff_missing=1
}

pyproject_stripped=""
[[ -f pyproject.toml ]] && pyproject_stripped="$(strip_comments pyproject.toml)"

if ! grep -qE "^\\[tool\\.ruff" <<<"${pyproject_stripped}"; then
  fail_ruff_check "pyproject.toml" \
    "Add a [tool.ruff] configuration block to pyproject.toml."
fi

if ! grep -qE "^\\[formatter\\.ruff\\]" <<<"${treefmt_stripped}"; then
  fail_ruff_check "treefmt.toml" \
    "Add a [formatter.ruff] entry to treefmt.toml."
fi

if ! grep -qE "\\bruff\\b" <<<"${lefthook_stripped}"; then
  fail_ruff_check "lefthook.yml" \
    "Add pre-commit commands that invoke 'ruff check' and 'ruff format --check' to lefthook.yml."
fi

# A single `task check` invocation satisfies both the lint and format
# gate (it dispatches through scripts/lint.sh and scripts/format.sh
# --check, each of which invokes ruff). Accept direct `ruff check` +
# `ruff format --check` as an equivalent alternative.
if ! grep -qE "\\btask check\\b" <<<"${workflows_stripped}" \
  && ! { grep -qE "\\bruff check\\b" <<<"${workflows_stripped}" \
    && grep -qE "\\bruff format --check\\b" <<<"${workflows_stripped}"; }; then
  fail_ruff_check ".github/workflows/*.yml" \
    "Add a workflow step that runs 'task check' (or both 'ruff check' and 'ruff format --check' directly)."
fi

if [[ ${ruff_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: ruff is configured in pyproject.toml, wired into treefmt and lefthook, and gated in CI."

# pip-audit must be wired into at least one CI workflow
# (.claude/instructions/python.md Tooling).
if ! grep -qE "\\bpip-audit\\b" <<<"${workflows_stripped}"; then
  echo "verify-standards: 'pip-audit' is not invoked in any .github/workflows/*.yml file." >&2
  echo "  Add a workflow step that runs 'pip-audit' (see .github/workflows/security.yml)." >&2
  exit 1
fi

echo "verify-standards: pip-audit is wired into CI."

# OpenSSF Scorecard must run on a schedule and gate on an aggregate
# score floor, per design/SELF_ASSESSMENT.md → "OpenSSF Scorecard"
# and the issue closure criteria for #108.
scorecard_workflow=".github/workflows/scorecard.yml"
if [[ ! -f ${scorecard_workflow} ]]; then
  echo "verify-standards: ${scorecard_workflow} is missing." >&2
  echo "  Add a Scorecard workflow using ossf/scorecard-action." >&2
  exit 1
fi
if ! grep -qE "ossf/scorecard-action" "${scorecard_workflow}"; then
  echo "verify-standards: ${scorecard_workflow} does not invoke ossf/scorecard-action." >&2
  exit 1
fi
if ! grep -qE "^\s*-\s*cron:" "${scorecard_workflow}"; then
  echo "verify-standards: ${scorecard_workflow} must run on a cron schedule." >&2
  exit 1
fi
if ! grep -qE "SCORECARD_MIN_SCORE" "${scorecard_workflow}"; then
  echo "verify-standards: ${scorecard_workflow} must gate on an aggregate score floor (SCORECARD_MIN_SCORE)." >&2
  exit 1
fi

echo "verify-standards: OpenSSF Scorecard workflow is present, scheduled, and gated on SCORECARD_MIN_SCORE."

# DCO sign-off must be checked on every PR per design/SSDF.md PS.1.1
# and the issue closure criteria for #116.
dco_workflow=".github/workflows/dco.yml"
if [[ ! -f ${dco_workflow} ]]; then
  echo "verify-standards: ${dco_workflow} is missing." >&2
  echo "  Add a DCO sign-off check workflow (see CONTRIBUTING.md → 'DCO sign-off')." >&2
  exit 1
fi
if ! grep -qE "^\s*-\s*pull_request\b|^\s*pull_request:" "${dco_workflow}"; then
  echo "verify-standards: ${dco_workflow} must trigger on pull_request events." >&2
  exit 1
fi
if ! grep -qE "Signed-off-by" "${dco_workflow}"; then
  echo "verify-standards: ${dco_workflow} must check for a Signed-off-by trailer." >&2
  exit 1
fi

echo "verify-standards: DCO sign-off workflow is present and triggers on pull_request."

# Post-incident review template must exist per design/SSDF.md RV.2.1 /
# RV.3.1 / RV.3.2 / RV.3.3 / RV.3.4 and the issue closure criteria for
# #131. The directory hosts TEMPLATE.md + README.md plus any numbered
# PIR files; only the scaffolding is enforced here.
pir_dir="design/vulnerability-reviews"
if [[ ! -d ${pir_dir} ]]; then
  echo "verify-standards: ${pir_dir}/ directory is missing." >&2
  echo "  Add the post-incident review scaffolding (see SECURITY.md → Post-incident review)." >&2
  exit 1
fi
for pir_file in TEMPLATE.md README.md; do
  if [[ ! -f "${pir_dir}/${pir_file}" ]]; then
    echo "verify-standards: ${pir_dir}/${pir_file} is missing." >&2
    exit 1
  fi
done
for pir_section in "Root cause" "Similar-vulnerability search" "Patterns over time" "Remediation" "Preventive follow-ups"; do
  if ! grep -qF "## ${pir_section}" "${pir_dir}/TEMPLATE.md"; then
    echo "verify-standards: ${pir_dir}/TEMPLATE.md missing required section '## ${pir_section}'." >&2
    exit 1
  fi
done

echo "verify-standards: post-incident review template is present with all required sections."

# Type checking per .claude/instructions/python.md (Tooling: "mypy and
# pyright — type checking. Run both in CI.") and the deterministic
# regression check in issue #48:
#
#   - pyproject.toml declares [tool.mypy] with strict = true.
#   - pyrightconfig.json exists at the repo root.
#   - At least one CI workflow runs both mypy and pyright.
#
# Scoped to workflows_only_stripped + `run:` prefix (same pattern as the
# treefmt/ripsecrets checks) so the tools appearing only in
# dev-dependency installs can't satisfy the CI gate.

typecheck_missing=0

fail_typecheck_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  typecheck_missing=1
}

if ! grep -qE "^\\[tool\\.mypy\\]" <<<"${pyproject_stripped}"; then
  fail_typecheck_check \
    "pyproject.toml is missing a [tool.mypy] configuration block." \
    "Add [tool.mypy] with strict = true (see .claude/instructions/python.md)."
elif ! grep -qE "^strict[[:space:]]*=[[:space:]]*true" <<<"${pyproject_stripped}"; then
  fail_typecheck_check \
    "pyproject.toml's [tool.mypy] block does not set strict = true." \
    "Add 'strict = true' to the [tool.mypy] block; relax individual modules via [[tool.mypy.overrides]] as needed."
fi

if [[ ! -f pyrightconfig.json ]]; then
  fail_typecheck_check \
    "pyrightconfig.json is missing from the repo root." \
    "Create pyrightconfig.json with typeCheckingMode: \"strict\" (see .claude/instructions/python.md)."
fi

# Both mypy and pyright must appear on a workflow `run:` line. Using the
# workflows_only_stripped corpus (workflows/*.yml, no actions/) keeps the
# check honest — mypy/pyright also appear in dev-dependency install
# steps, which don't count as "gated in CI".
if ! grep -qE "run:[[:space:]]*[^\\n]*\\bmypy\\b" <<<"${workflows_only_stripped}" \
  && ! grep -qE "run:[[:space:]]*task[[:space:]]+typecheck" <<<"${workflows_only_stripped}"; then
  fail_typecheck_check \
    "no .github/workflows/*.yml runs 'mypy' (or 'task typecheck')." \
    "Add a workflow step that runs 'task typecheck' (see .github/workflows/typecheck.yml)."
fi

if ! grep -qE "run:[[:space:]]*[^\\n]*\\bpyright\\b" <<<"${workflows_only_stripped}" \
  && ! grep -qE "run:[[:space:]]*task[[:space:]]+typecheck" <<<"${workflows_only_stripped}"; then
  fail_typecheck_check \
    "no .github/workflows/*.yml runs 'pyright' (or 'task typecheck')." \
    "Add a workflow step that runs 'task typecheck' (see .github/workflows/typecheck.yml)."
fi

if [[ ${typecheck_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: mypy (strict) and pyright are configured and gated in CI."

# Ratchet-list co-source check: every module relaxed on the mypy side
# must have a matching relaxation on the pyright side, and vice versa.
# Without this, a rename or delete that touches one file leaves the
# other stale — the file silently returns to strict under the
# un-synchronised checker (which may then report pre-existing errors
# in a surprise PR) or stays relaxed forever (hiding regressions).
# Mutual citation in the file comments makes the co-edit conventional;
# this check makes it enforced.
#
# The mypy side carries two *kinds* of relaxation that we care about:
#
#   - ``ignore_errors = true`` — the whole module is skipped; pairs
#     with an entry in pyrightconfig.json's top-level ``ignore`` list.
#   - Per-diagnostic relaxations such as
#     ``disallow_untyped_defs = false`` — individual strictness flags
#     are turned off (e.g. the tests.* override used for pytest
#     fixture-parameter ergonomics). These pair with a pyright
#     ``executionEnvironments`` entry whose ``root`` covers the same
#     source tree, which is where pyright's per-scope diagnostic
#     relaxations live.
#
# Historically only the first kind was checked, so PR #171 narrowed
# the tests.* override to per-diagnostic relaxations without the
# safeguard catching a matching pyright drift (see issue #175). The
# check below now covers both kinds.

if [[ -f pyproject.toml && -f pyrightconfig.json ]]; then
  ratchet_drift="$(
    python3 - <<'PY'
import json
import pathlib
import sys
import tomllib

with open("pyproject.toml", "rb") as f:
    pyproject = tomllib.load(f)
with open("pyrightconfig.json") as f:
    pyright = json.load(f)

# Any disallow_* flag set to false (the mypy equivalent of a pyright
# per-diagnostic relaxation) triggers the executionEnvironments-match
# check. The set is kept deliberately narrow to disallow_*:
# ignore_missing_imports applies to untyped third-party packages
# (e.g. keyring) whose shape isn't something pyright's scoped rules
# mirror, and a warn_* flag doesn't relax strictness in the same way.
DISALLOW_FLAGS = (
    "disallow_untyped_defs",
    "disallow_incomplete_defs",
    "disallow_untyped_calls",
    "disallow_any_generics",
    "disallow_untyped_decorators",
    "disallow_subclassing_any",
    "disallow_any_unimported",
    "disallow_any_expr",
    "disallow_any_decorated",
    "disallow_any_explicit",
)

mypy_ignore_modules: set[str] = set()
mypy_relaxed_modules: set[str] = set()
for override in pyproject.get("tool", {}).get("mypy", {}).get("overrides", []):
    mods = override.get("module", [])
    if isinstance(mods, str):
        mods = [mods]
    cleaned = [m.rstrip(".*").rstrip(".") for m in mods]
    if override.get("ignore_errors", False):
        mypy_ignore_modules.update(cleaned)
    if any(override.get(flag) is False for flag in DISALLOW_FLAGS):
        mypy_relaxed_modules.update(cleaned)


def module_to_path(mod: str) -> str:
    path = mod.replace(".", "/")
    candidates = [
        f"src/{path}.py",
        f"src/{path}",
        f"{path}",
    ]
    for c in candidates:
        if pathlib.Path(c).exists():
            return c
    return f"src/{path}"


expected_pyright_ignore = {module_to_path(m) for m in mypy_ignore_modules}
actual_pyright_ignore = set(pyright.get("ignore", []))

missing_from_pyright_ignore = expected_pyright_ignore - actual_pyright_ignore
missing_from_mypy_ignore = actual_pyright_ignore - expected_pyright_ignore

expected_pyright_envs = {module_to_path(m) for m in mypy_relaxed_modules}
actual_pyright_envs = {
    env.get("root", "")
    for env in pyright.get("executionEnvironments", [])
    if env.get("root")
}

# Only flag pyright executionEnvironments whose root falls inside one
# of the include paths that also carry per-source relaxations — the
# root can legitimately exist purely for a non-strictness reason (e.g.
# a different Python version), so we require a real mypy side match
# only when the pyright env overrides one of the DISALLOW_FLAG
# counterparts below.
PYRIGHT_DIAGNOSTIC_EQUIVALENTS = (
    "reportMissingParameterType",
    "reportUnknownParameterType",
    "reportUnknownArgumentType",
    "reportUnknownVariableType",
    "reportUnknownMemberType",
    "reportUnknownLambdaType",
    "reportMissingTypeArgument",
)
pyright_envs_relaxing_diagnostics = {
    env.get("root", "")
    for env in pyright.get("executionEnvironments", [])
    if env.get("root")
    and any(
        env.get(diag) == "none" or env.get(diag) == "warning"
        for diag in PYRIGHT_DIAGNOSTIC_EQUIVALENTS
    )
}

missing_from_pyright_envs = expected_pyright_envs - pyright_envs_relaxing_diagnostics
missing_from_mypy_relaxed = pyright_envs_relaxing_diagnostics - expected_pyright_envs

problems: list[tuple[str, list[str]]] = []
if missing_from_pyright_ignore:
    problems.append(
        (
            "mypy ignore_errors entries with no matching pyrightconfig.json 'ignore' path",
            sorted(missing_from_pyright_ignore),
        )
    )
if missing_from_mypy_ignore:
    problems.append(
        (
            "pyrightconfig.json 'ignore' paths with no matching mypy ignore_errors override",
            sorted(missing_from_mypy_ignore),
        )
    )
if missing_from_pyright_envs:
    problems.append(
        (
            "mypy disallow_* = false overrides with no matching pyright executionEnvironments root",
            sorted(missing_from_pyright_envs),
        )
    )
if missing_from_mypy_relaxed:
    problems.append(
        (
            "pyright executionEnvironments roots relaxing reportMissing/reportUnknown* with no matching mypy disallow_* = false override",
            sorted(missing_from_mypy_relaxed),
        )
    )

for heading, entries in problems:
    print(heading + ":")
    for entry in entries:
        print(f"  - {entry}")

if problems:
    sys.exit(1)
PY
  )" || {
    echo "verify-standards: mypy/pyright ratchet lists are out of sync." >&2
    echo "  Every [[tool.mypy.overrides]] entry that relaxes strictness in" >&2
    echo "  pyproject.toml must have a matching relaxation in" >&2
    echo "  pyrightconfig.json (top-level 'ignore' for ignore_errors = true;" >&2
    echo "  an 'executionEnvironments' root with a relaxed reportUnknown* /" >&2
    echo "  reportMissing* diagnostic for per-flag disallow_* = false), and" >&2
    echo "  vice versa. Drift:" >&2
    while IFS= read -r line; do
      echo "  ${line}" >&2
    done <<<"${ratchet_drift}"
    exit 1
  }

  echo "verify-standards: mypy and pyright ratchet lists are in sync."
fi

# pytest-cov coverage floor per
# .claude/instructions/testing-standards.md (Coverage) and
# .claude/instructions/python.md (Tooling: pytest-cov). The
# deterministic regression check from issue #37:
#
#   - pyproject.toml (or pytest.ini) sets --cov-fail-under=<N> in
#     pytest's addopts (N > 0).
#   - At least one CI workflow invokes `pytest --cov` (directly or
#     via a task dispatcher that reaches pytest through pytest.ini
#     addopts).

coverage_missing=0

fail_coverage_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  coverage_missing=1
}

if ! grep -qE -- "--cov-fail-under=[1-9][0-9]*" <<<"${pyproject_stripped}"; then
  fail_coverage_check \
    "pyproject.toml pytest addopts does not set --cov-fail-under=<N>." \
    "Add '--cov-fail-under=<N>' to [tool.pytest.ini_options].addopts (see .claude/instructions/testing-standards.md Coverage)."
fi

# The CI gate is satisfied whether pytest is invoked directly (with
# --cov on the command line) or transitively through `task test`
# (pytest then picks up --cov=... from pyproject.toml's addopts).
# Match `pytest --cov`, a direct task invocation that reaches pytest,
# or the `task test` dispatcher pattern used by the Test workflow.
if ! grep -qE "run:[[:space:]]*[^\\n]*pytest[^\\n]*--cov" <<<"${workflows_only_stripped}" \
  && ! grep -qE "run:[[:space:]]*task[[:space:]]+test" <<<"${workflows_only_stripped}"; then
  fail_coverage_check \
    "no .github/workflows/*.yml runs 'pytest --cov' (or 'task test' which picks up --cov from pyproject.toml)." \
    "Add a workflow step that runs 'task test' (see .github/workflows/test.yml)."
fi

if [[ ${coverage_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: pytest-cov fail-under threshold set in pyproject.toml and gated in CI."

# CONTRIBUTING.md must exist and contain the four required sections per
# .claude/instructions/release-and-hygiene.md.

contributing_missing=0

fail_contributing_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  contributing_missing=1
}

if [[ ! -f CONTRIBUTING.md ]]; then
  fail_contributing_check \
    "CONTRIBUTING.md is missing from the repo root." \
    "Add CONTRIBUTING.md covering dev setup, testing, release, and commit signing."
else
  # Parallel arrays (bash 3.2-compatible): section_names[i] pairs with section_patterns[i].
  section_names=(
    dev-setup
    testing
    release
    commit-signing
  )
  section_patterns=(
    "## Dev setup|## Development environment setup|## Getting started|## Setup"
    # This project collapses testing and the task catalogue into one section
    # ("## Running tasks"). Accept that heading as well as a dedicated testing
    # section heading so the check stays valid if the two are split later.
    "## Running tasks|## Testing|## Running tests"
    "## Release"
    "## Commit signing"
  )

  for i in "${!section_names[@]}"; do
    if ! grep -qiE "${section_patterns[${i}]}" CONTRIBUTING.md; then
      fail_contributing_check \
        "CONTRIBUTING.md is missing a '${section_names[${i}]}' section." \
        "Add a section matching: ${section_patterns[${i}]}"
    fi
  done
fi

if [[ ${contributing_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: CONTRIBUTING.md exists with dev-setup, testing, release, and commit-signing sections."

# ADR discipline per .claude/instructions/design.md. Every file under
# design/decisions/ other than README.md / TEMPLATE.md must:
#   - contain ## Context, ## Decision, and ## Consequences sections
#     (case-insensitive, anchored to start of line),
#   - be linked from design/decisions/README.md (filename appears as a
#     markdown link target).

adr_missing=0

fail_adr_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  adr_missing=1
}

ADR_DIR="design/decisions"
ADR_INDEX="${ADR_DIR}/README.md"

if [[ ! -d "${ADR_DIR}" ]]; then
  fail_adr_check \
    "${ADR_DIR}/ is missing." \
    "Create ${ADR_DIR}/ with README.md, TEMPLATE.md, and at least one ADR."
elif [[ ! -f "${ADR_INDEX}" ]]; then
  fail_adr_check \
    "${ADR_INDEX} is missing." \
    "Create ${ADR_INDEX} listing every ADR by filename link."
else
  index_content="$(cat "${ADR_INDEX}")"
  while IFS= read -r adr; do
    [[ -f "${adr}" ]] || continue
    base="$(basename "${adr}")"
    [[ "${base}" == "README.md" || "${base}" == "TEMPLATE.md" ]] && continue

    # strip_comments eats Markdown headings (they start with `#`), so the
    # ADR gate reads the raw file. The required sections are unambiguous
    # — no code-block fencing concern inside an ADR section heading.
    for section in Context Decision Consequences; do
      if ! grep -qiE "^##[[:space:]]+${section}([[:space:]]|$)" "${adr}"; then
        fail_adr_check \
          "${adr} is missing a '## ${section}' section." \
          "Add a '## ${section}' heading (see ${ADR_DIR}/TEMPLATE.md)."
      fi
    done

    # Match as a Markdown link target `](filename)` rather than a bare
    # substring so a filename mentioned in prose doesn't spuriously
    # satisfy the check, and a filename that happens to be a suffix of
    # another entry can't substring-match it.
    escaped_base="${base//./\\.}"
    if ! grep -qE "\]\(${escaped_base}\)" <<<"${index_content}"; then
      fail_adr_check \
        "${adr} is not linked from ${ADR_INDEX}." \
        "Add an entry to ${ADR_INDEX} with a Markdown link to ${base}."
    fi
  done < <(find "${ADR_DIR}" -type f -name '*.md' -print)
fi

if [[ ${adr_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: ADRs under ${ADR_DIR}/ all have Context/Decision/Consequences sections and are linked from ${ADR_INDEX}."

# QM / SIL declaration per .claude/instructions/design.md. design/ASSURANCE.md
# must exist, declare at least one of QM / SIL, and list required activities
# and evidence.

assurance_missing=0

fail_assurance_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  assurance_missing=1
}

ASSURANCE_FILE="design/ASSURANCE.md"

if [[ ! -f "${ASSURANCE_FILE}" ]]; then
  fail_assurance_check \
    "${ASSURANCE_FILE} is missing." \
    "Create ${ASSURANCE_FILE} declaring a QM (ISO 9000) or SIL (IEC 61508) level."
else
  # strip_comments eats Markdown headings (they start with `#`), so the
  # ASSURANCE gate reads the raw file.
  if ! grep -qE "\\b(QM|SIL)\\b" "${ASSURANCE_FILE}"; then
    fail_assurance_check \
      "${ASSURANCE_FILE} does not declare a QM or SIL level." \
      "Name the chosen level (QM or SIL N) in a top-level heading or paragraph."
  fi

  if ! grep -qiE "^##[[:space:]]+Required activities" "${ASSURANCE_FILE}"; then
    fail_assurance_check \
      "${ASSURANCE_FILE} is missing a '## Required activities' section." \
      "List the activities required by the declared level."
  fi

  if ! grep -qiE "^##[[:space:]]+Required evidence" "${ASSURANCE_FILE}"; then
    fail_assurance_check \
      "${ASSURANCE_FILE} is missing a '## Required evidence' section." \
      "List the evidence that demonstrates conformance to the declared level."
  fi
fi

if [[ ${assurance_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: ${ASSURANCE_FILE} declares a QM/SIL level with required activities and evidence."

# CHANGELOG.md must exist per .claude/instructions/release-and-hygiene.md.
# The `## [Unreleased]` section is intentionally absent: semantic-release
# (ADR 0026) owns the file post-migration and prepends a new versioned
# section on each release rather than promoting [Unreleased] content.

if [[ ! -f CHANGELOG.md ]]; then
  echo "verify-standards: CHANGELOG.md is missing from the repo root." >&2
  echo "  Add CHANGELOG.md following the Keep-a-Changelog format." >&2
  exit 1
fi

echo "verify-standards: CHANGELOG.md exists."

# LICENSE.md must exist and README.md must link to it from a ## License section
# per .claude/instructions/release-and-hygiene.md.

license_missing=0

if [[ ! -f LICENSE.md ]]; then
  echo "verify-standards: LICENSE.md is missing from the repo root." >&2
  echo "  Add LICENSE.md (default: MIT) at the repo root." >&2
  license_missing=1
fi

if [[ ! -f README.md ]]; then
  echo "verify-standards: README.md is missing from the repo root." >&2
  license_missing=1
elif ! grep -qE "^## License" README.md; then
  echo "verify-standards: README.md does not contain a '## License' section." >&2
  echo "  Add a '## License' section to README.md linking to LICENSE.md." >&2
  license_missing=1
elif ! grep -qiE "\\[.*\\]\\(LICENSE\\.md\\)" README.md; then
  echo "verify-standards: README.md '## License' section does not link to LICENSE.md." >&2
  echo "  Add a markdown link to LICENSE.md in the '## License' section of README.md." >&2
  license_missing=1
fi

if [[ ${license_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: LICENSE.md exists and README.md links to it from a License section."

# SECURITY.md must exist and contain the required sections per
# .claude/instructions/release-and-hygiene.md and .claude/instructions/design.md.

security_missing=0

fail_security_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  security_missing=1
}

if [[ ! -f SECURITY.md ]]; then
  fail_security_check \
    "SECURITY.md is missing from the repo root." \
    "Add SECURITY.md covering trust boundaries, threat model, key handling, revocation flow, audit surface, and vulnerability reporting."
else
  # Combined "name|pattern" entries kept sortable without parallel-array
  # misalignment risk. keep-sorted maintains alphabetical order; the pipe
  # delimiter separates the human-readable name from the grep pattern.
  security_sections=(
    # keep-sorted start
    "application-security-standard|## Application security standard|Application security standard"
    "audit-surface|## Audit surface|## Audit log"
    "cybersecurity-standard|## Cybersecurity standard|Cybersecurity standard"
    "key-handling|## Key handling"
    "revocation-flow|## Revocation flow"
    "sdlc-standard|## SDLC standard|SDLC standard"
    "threat-model|## Threat model"
    "trust-boundaries|## Trust boundaries|## Trust boundary"
    "vulnerability-reporting|## Vulnerability reporting|## Reporting vulnerabilities"
    # keep-sorted end
  )

  for entry in "${security_sections[@]}"; do
    section_name="${entry%%|*}"
    section_pattern="${entry#*|}"
    if ! grep -qiE "${section_pattern}" SECURITY.md; then
      fail_security_check \
        "SECURITY.md is missing a '${section_name}' section." \
        "Add a section matching: ${section_pattern}"
    fi
  done
fi

if [[ ${security_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: SECURITY.md exists with all required sections including the cybersecurity, SDLC, and application security standards."

# install.sh must exist at the repo root and be executable per
# .claude/instructions/release-and-hygiene.md.

if [[ ! -f install.sh ]]; then
  echo "verify-standards: install.sh is missing from the repo root." >&2
  echo "  Add install.sh following the bash script conventions in .claude/instructions/bash.md." >&2
  exit 1
fi

if [[ ! -x install.sh ]]; then
  echo "verify-standards: install.sh exists but is not executable." >&2
  echo "  Run 'chmod +x install.sh' and commit the mode change." >&2
  exit 1
fi

echo "verify-standards: install.sh exists and is executable."

# lefthook hooks must be installed locally so the pre-commit commands
# configured in lefthook.yml actually fire. Skipped when CI=true — CI
# gates the same checks explicitly via workflow steps, so a fresh
# checkout doesn't need the local hook shim. A local clone with
# lefthook.yml present but no pre-commit shim is a silent failure mode
# (commits land without the configured checks), which this gate catches.

if [[ -f lefthook.yml && -z "${CI:-}" ]]; then
  hooks_dir="$(git rev-parse --git-path hooks)"
  pre_commit_hook="${hooks_dir}/pre-commit"
  if [[ ! -f "${pre_commit_hook}" ]] || ! grep -q lefthook "${pre_commit_hook}"; then
    echo "verify-standards: lefthook hooks are not installed in this clone." >&2
    echo "  lefthook.yml is present but ${pre_commit_hook} is missing or is not a lefthook shim." >&2
    echo "  Run 'task install-hooks' to install them." >&2
    exit 1
  fi
  echo "verify-standards: lefthook pre-commit hook is installed."
fi

# GitHub repository About metadata must be populated per
# .claude/instructions/release-and-hygiene.md. Skipped when 'gh' is not
# available or not authenticated (e.g. local dev without credentials).

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  repo_meta="$(gh repo view --json description,repositoryTopics 2>/dev/null || true)"
  if [[ -n "${repo_meta}" ]]; then
    mapfile -t _gh_fields < <(
      python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print(d.get('description', ''))
print(len(d.get('repositoryTopics', [])))
" "${repo_meta}"
    )
    repo_description="${_gh_fields[0]:-}"
    repo_topics="${_gh_fields[1]:-0}"

    gh_meta_missing=0
    if [[ -z "${repo_description}" ]]; then
      echo "verify-standards: GitHub repo 'About' description is empty." >&2
      echo "  Set it via 'gh repo edit --description \"...\"'." >&2
      gh_meta_missing=1
    fi
    if [[ "${repo_topics}" -eq 0 ]]; then
      echo "verify-standards: GitHub repo has no topics set." >&2
      echo "  Set them via 'gh repo edit --add-topic <topic>'." >&2
      gh_meta_missing=1
    fi
    if [[ ${gh_meta_missing} -ne 0 ]]; then
      exit 1
    fi
    echo "verify-standards: GitHub repo About metadata (description, topics) is populated."
  fi
else
  echo "verify-standards: 'gh' not available or not authenticated; skipping GitHub metadata check."
fi

# config format: config.py files must not reference config.json or use json.load
# (.claude/instructions/service-design.md — YAML config).
config_json_bad=0
for cfg_file in src/agent_auth/config.py src/things_bridge/config.py; do
  if [[ -f "${cfg_file}" ]]; then
    if grep -qE "config\.json|json\.load" "${cfg_file}"; then
      echo "verify-standards: ${cfg_file} references 'config.json' or uses json.load." >&2
      echo "  Config must be loaded from config.yaml via yaml.safe_load." >&2
      config_json_bad=1
    fi
  fi
done
if [[ ${config_json_bad} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: config files use YAML (no config.json or json.load in config.py)."

# API versioning: every registered HTTP route (outside /health and /metrics)
# must match ^/(agent-auth|things-bridge)/v[0-9]+/
# (.claude/instructions/service-design.md — URL-versioned APIs; see
# design/DESIGN.md "API Versioning Policy" for the health/metrics
# convention). /metrics is unimplemented today (#26) but is pre-excluded
# so the check stays honest once the endpoint lands.
# agent-auth/server.py uses `self.path ==`; things_bridge/server.py uses
# bare `path ==` / `path.startswith` — both patterns are checked.
unversioned_routes=$(grep -En \
  '(self\.path|[^_]path) (==|\.startswith\() "/' \
  src/agent_auth/server.py src/things_bridge/server.py 2>/dev/null \
  | grep -v '/health' \
  | grep -v '/metrics' \
  | grep -v '/v[0-9]\+/' \
  | grep -v '# unversioned' || true)
if [[ -n "${unversioned_routes}" ]]; then
  echo "verify-standards: unversioned HTTP routes found in server files:" >&2
  echo "${unversioned_routes}" >&2
  echo "  All endpoints (except /health and /metrics) must use the /v1/ namespace." >&2
  exit 1
fi

echo "verify-standards: all non-health/metrics HTTP routes are versioned (/v1/)."

# Audit schema contract tests: tests/test_audit_schema.py must exist and
# reference each documented event kind
# (.claude/instructions/release-and-hygiene.md — structured output schemas).
audit_schema_file="tests/test_audit_schema.py"
if [[ ! -f "${audit_schema_file}" ]]; then
  echo "verify-standards: ${audit_schema_file} does not exist." >&2
  echo "  Create schema-contract tests for every documented audit event kind." >&2
  exit 1
fi

audit_events=(
  token_created token_refreshed token_reissued token_revoked token_rotated
  scopes_modified reissue_denied validation_allowed validation_denied
  approval_granted approval_denied
)
audit_missing=0
for event in "${audit_events[@]}"; do
  if ! grep -q "\"${event}\"" "${audit_schema_file}"; then
    echo "verify-standards: audit event '${event}' not referenced in ${audit_schema_file}." >&2
    audit_missing=1
  fi
done
if [[ ${audit_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: ${audit_schema_file} exists and references all documented audit event kinds."

# Error taxonomy contract tests: tests/test_error_taxonomy.py must exist and
# reference each documented error code
# (.claude/instructions/service-design.md — stable error taxonomy).
error_taxonomy_file="tests/test_error_taxonomy.py"
if [[ ! -f "${error_taxonomy_file}" ]]; then
  echo "verify-standards: ${error_taxonomy_file} does not exist." >&2
  echo "  Create contract tests for every documented error code in design/error-codes.md." >&2
  exit 1
fi

error_codes=(
  malformed_request invalid_token token_expired token_revoked scope_denied
  family_revoked refresh_token_expired refresh_token_reuse_detected
  refresh_token_still_valid reissue_denied missing_token not_found
  unauthorized authz_unavailable things_permission_denied things_unavailable
  method_not_allowed
)
error_missing=0
for code in "${error_codes[@]}"; do
  if ! grep -q "\"${code}\"" "${error_taxonomy_file}"; then
    echo "verify-standards: error code '${code}' not referenced in ${error_taxonomy_file}." >&2
    error_missing=1
  fi
done
if [[ ${error_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: ${error_taxonomy_file} exists and references all documented error codes."

# OpenAPI specs: openapi/agent-auth.v1.yaml and openapi/things-bridge.v1.yaml
# must exist, and tests/test_openapi_spec.py must reference both so route and
# error-taxonomy parity are enforced on every PR (#117).
openapi_missing=0
for spec in openapi/agent-auth.v1.yaml openapi/things-bridge.v1.yaml; do
  if [[ ! -f "${spec}" ]]; then
    echo "verify-standards: ${spec} is missing." >&2
    openapi_missing=1
  fi
done

openapi_contract_test="tests/test_openapi_spec.py"
if [[ ! -f "${openapi_contract_test}" ]]; then
  echo "verify-standards: ${openapi_contract_test} is missing." >&2
  echo "  Add contract tests that diff spec paths against the server handlers." >&2
  openapi_missing=1
else
  for spec in agent-auth.v1.yaml things-bridge.v1.yaml; do
    if ! grep -q "${spec}" "${openapi_contract_test}"; then
      echo "verify-standards: ${openapi_contract_test} does not reference ${spec}." >&2
      openapi_missing=1
    fi
  done
fi

if [[ ${openapi_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: openapi/*.v1.yaml exist and ${openapi_contract_test} references both."

# Health endpoints per .claude/instructions/service-design.md
# ("Health endpoint") and the deterministic regression check from
# issue #25:
#
#   - /agent-auth/health is registered in src/agent_auth/server.py
#     and /things-bridge/health is registered in src/things_bridge/server.py.
#   - At least one test function per route asserts a healthy (200)
#     response, and at least one asserts an unhealthy subsystem-failure
#     response (503 for agent-auth when the store ping fails; 502 for
#     things-bridge when the authz upstream is unavailable).
#
# The check is scoped per-function (not per-file): without that,
# tests/test_error_taxonomy.py would satisfy the gate for any route
# because it mentions every route and every status code somewhere in
# the file.

health_drift="$(
  python3 - <<'PY'
import pathlib
import re
import sys

# Accept either the literal path or a call to ``health_url()`` — the
# integration fixtures expose the latter to let tests flip between
# direct and in-process transports without hard-coding the path.
SERVICES = (
    ("agent-auth", "src/agent_auth/server.py", 503),
    ("things-bridge", "src/things_bridge/server.py", 502),
)

def function_blocks(source: str) -> list[str]:
    return re.split(r"\n(?=(?:async )?def )", source)


def block_targets_route(block: str, route: str, service: str) -> bool:
    if route in block:
        return True
    # ``health_url()`` is only surfaced by the service's own integration
    # fixtures, so it's unambiguous which route it references once the
    # file's service scope is known.
    if "health_url()" in block and service in block:
        return True
    return False


errors: list[str] = []

for service, server_path, unhealthy_status in SERVICES:
    route = f"/{service}/health"
    server_src = pathlib.Path(server_path).read_text()
    if f'"{route}"' not in server_src:
        errors.append(f"{route} is not registered in {server_path}")
        continue

    healthy_found = False
    unhealthy_found = False
    for test_file in sorted(pathlib.Path("tests").rglob("*.py")):
        source = test_file.read_text()
        if route not in source and "health_url()" not in source:
            continue
        # ``health_url()`` fixtures live under the matching service
        # directory; fall back to checking the whole file's service
        # context when the literal route isn't present.
        file_service_hint = service if service in str(test_file) or service in source else ""
        if route not in source and not file_service_hint:
            continue
        for block in function_blocks(source):
            if not block_targets_route(block, route, service):
                continue
            if re.search(r"status\s*==\s*200", block):
                healthy_found = True
            if re.search(rf"status\s*==\s*{unhealthy_status}", block):
                unhealthy_found = True

    if not healthy_found:
        errors.append(f"no test function asserts status == 200 on {route}")
    if not unhealthy_found:
        errors.append(
            f"no test function asserts status == {unhealthy_status} on {route}"
        )

for err in errors:
    print(err)
if errors:
    sys.exit(1)
PY
)" || {
  echo "verify-standards: health endpoint coverage gaps:" >&2
  while IFS= read -r line; do
    echo "  - ${line}" >&2
  done <<<"${health_drift}"
  exit 1
}

echo "verify-standards: /agent-auth/health and /things-bridge/health are registered with healthy + unhealthy test coverage."

# ---------------------------------------------------------------------------
# Function-to-test coverage is gated in CI (no continue-on-error).
# ---------------------------------------------------------------------------
# The verify-function-tests workflow must fail CI when any leaf function in
# design/functional_decomposition.yaml lacks a matching
# @pytest.mark.covers_function(...) annotation. A continue-on-error on the
# verify step silently swallows regressions — enforce its absence here.
function_tests_workflow=".github/workflows/verify-function-tests.yml"
if [[ -f "${function_tests_workflow}" ]]; then
  if ! command -v yq >/dev/null 2>&1; then
    echo "verify-standards: 'yq' is required to inspect ${function_tests_workflow}." >&2
    exit 1
  fi
  verify_step_has_continue_on_error="$(
    yq eval -o=json '.jobs[].steps[] | select(.run // "" | test("verify-function-tests")) | .["continue-on-error"] // false' \
      "${function_tests_workflow}" 2>/dev/null
  )"
  if [[ "${verify_step_has_continue_on_error}" == "true" ]]; then
    echo "verify-standards: ${function_tests_workflow} has 'continue-on-error: true' on the verify step." >&2
    echo "  Function-to-test coverage regressions must fail CI. Remove the continue-on-error." >&2
    exit 1
  fi
  echo "verify-standards: ${function_tests_workflow} gates function-to-test coverage without continue-on-error."
fi

# ---------------------------------------------------------------------------
# Mutation testing on security-critical paths.
# ---------------------------------------------------------------------------
# .claude/instructions/testing-standards.md (Coverage — "Mutation testing
# on security-critical paths") requires:
#   1. A mutation-testing tool configured in pyproject.toml.
#   2. A scheduled CI workflow that invokes it.
#   3. A documented score threshold.
#
# The check is deliberately agnostic between mutmut / cosmic-ray — it
# only asserts that one of the two config sections exists. The threshold
# field name tracks the tool choice: [tool.mutation_score].fail_under.
if ! python3 -c "
import sys, tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text())
tool = data.get('tool', {})
if 'mutmut' not in tool and 'cosmic_ray' not in tool:
    sys.exit('no [tool.mutmut] or [tool.cosmic_ray] section in pyproject.toml')
threshold = tool.get('mutation_score', {}).get('fail_under')
if threshold is None:
    sys.exit('no [tool.mutation_score].fail_under threshold in pyproject.toml')
" 2>/tmp/verify-standards-mutation.err; then
  echo "verify-standards: mutation testing is not configured:" >&2
  cat /tmp/verify-standards-mutation.err >&2
  echo "  See .claude/instructions/testing-standards.md § Coverage and ADR 0021." >&2
  rm -f /tmp/verify-standards-mutation.err
  exit 1
fi
rm -f /tmp/verify-standards-mutation.err

# Require at least one workflow file under .github/workflows/ that
# both has a `schedule:` trigger AND runs `task mutation-test` or calls
# mutmut directly. Matching on the Taskfile shim keeps us robust if
# the workflow ever inlines the commands.
mutation_workflow_found=0
for wf in .github/workflows/*.yml; do
  [[ -f "${wf}" ]] || continue
  if yq eval '.on | has("schedule")' "${wf}" 2>/dev/null | grep -qx true \
    && grep -qE "task[[:space:]]+mutation-test|mutmut[[:space:]]+run" "${wf}"; then
    mutation_workflow_found=1
    mutation_workflow="${wf}"
    break
  fi
done

if [[ "${mutation_workflow_found}" -eq 0 ]]; then
  echo "verify-standards: no scheduled workflow invokes the mutation-testing gate." >&2
  echo "  Add a .github/workflows/*.yml that triggers on 'schedule:' and runs" >&2
  echo "  'task mutation-test' (or 'mutmut run')." >&2
  exit 1
fi

echo "verify-standards: mutation testing configured ([tool.mutmut] / [tool.mutation_score]) and scheduled via ${mutation_workflow}."

# Metrics endpoints per .claude/instructions/service-design.md
# ("Metrics endpoint") and the deterministic regression check from
# issue #26:
#
#   - /agent-auth/metrics is registered in src/agent_auth/server.py
#     and /things-bridge/metrics is registered in src/things_bridge/server.py.
#   - At least one test function per route scrapes the endpoint (200
#     response) and validates that every declared metric name appears
#     in the response body. Name lists are hard-coded below so a
#     rename fails the gate deliberately.

metrics_drift="$(
  python3 - <<'PY'
import pathlib
import re
import sys

AGENT_AUTH_METRICS = (
    "http_server_request_duration_seconds",
    "http_server_active_requests",
    "agent_auth_token_operations_total",
    "agent_auth_validation_outcomes_total",
    "agent_auth_approval_outcomes_total",
)
THINGS_BRIDGE_METRICS = (
    "http_server_request_duration_seconds",
    "http_server_active_requests",
)
SERVICES = (
    ("agent-auth", "src/agent_auth/server.py", AGENT_AUTH_METRICS),
    ("things-bridge", "src/things_bridge/server.py", THINGS_BRIDGE_METRICS),
)


def function_blocks(source: str) -> list[str]:
    return re.split(r"\n(?=(?:async )?def )", source)


errors: list[str] = []

for service, server_path, required in SERVICES:
    route = f"/{service}/metrics"
    server_src = pathlib.Path(server_path).read_text()
    if f'"{route}"' not in server_src:
        errors.append(f"{route} is not registered in {server_path}")
        continue

    covered: set[str] = set()
    for test_file in sorted(pathlib.Path("tests").rglob("*.py")):
        source = test_file.read_text()
        if route not in source:
            continue
        for block in function_blocks(source):
            if route not in block:
                continue
            if not re.search(r"status\s*==\s*200", block):
                continue
            for name in required:
                if name in block:
                    covered.add(name)

    missing = [n for n in required if n not in covered]
    if missing:
        errors.append(
            f"{route}: no 200-response test block references metric(s) "
            + ", ".join(missing)
        )

for err in errors:
    print(err)
if errors:
    sys.exit(1)
PY
)" || {
  echo "verify-standards: metrics endpoint coverage gaps:" >&2
  while IFS= read -r line; do
    echo "  - ${line}" >&2
  done <<<"${metrics_drift}"
  exit 1
}

echo "verify-standards: /agent-auth/metrics and /things-bridge/metrics are registered with metric-name test coverage."

# Graceful SIGTERM / SIGINT shutdown per
# .claude/instructions/service-design.md ("Graceful shutdown") and the
# deterministic regression check from issue #32:
#
#   - Both server modules (src/agent_auth/server.py,
#     src/things_bridge/server.py) install a SIGTERM handler.
#   - At least one test under tests/ exercises SIGTERM shutdown
#     behaviour (grepping the literal token SIGTERM — the existing
#     subprocess-driven tests in tests/test_server_shutdown.py and
#     tests/test_things_bridge_shutdown.py already satisfy this).
#
# The gate is grep-only so it won't false-positive on a stale
# `# SIGTERM` comment after the real `signal.signal(signal.SIGTERM, ...)`
# invocation has been removed: strip_comments is applied first.

shutdown_missing=0

fail_shutdown_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  shutdown_missing=1
}

for server_file in src/agent_auth/server.py src/things_bridge/server.py; do
  if [[ ! -f "${server_file}" ]]; then
    fail_shutdown_check \
      "${server_file} is missing." \
      "Restore the server module or update this check."
    continue
  fi
  # strip_comments removes trailing comments so a commented-out mention
  # of signal.SIGTERM doesn't satisfy the gate after the real handler
  # installation has been removed.
  if ! strip_comments "${server_file}" | grep -qE "signal\.signal\([[:space:]]*signal\.SIGTERM"; then
    fail_shutdown_check \
      "${server_file} does not install a SIGTERM handler." \
      "Call 'signal.signal(signal.SIGTERM, ...)' in the server startup path (see .claude/instructions/service-design.md Graceful shutdown)."
  fi
done

# Look for at least one test anywhere under tests/ that references
# SIGTERM in executable code. ``test_server_shutdown.py`` and
# ``test_things_bridge_shutdown.py`` both satisfy this today via their
# ``invoke_installed_handler(signal.SIGTERM)`` + subprocess-driven
# coverage.
test_sigterm_hits="$(grep -rlE "\bSIGTERM\b" tests/ 2>/dev/null | grep -v __pycache__ || true)"
if [[ -z "${test_sigterm_hits}" ]]; then
  fail_shutdown_check \
    "no test under tests/ references SIGTERM." \
    "Add a test that sends SIGTERM to the server (or invokes the installed handler) and asserts a clean drain."
fi

if [[ ${shutdown_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: agent-auth and things-bridge install SIGTERM handlers and tests exercise shutdown behaviour."

# ---------------------------------------------------------------------------
# Fault-injection / chaos test layer.
# ---------------------------------------------------------------------------
# .claude/instructions/testing-standards.md (Coverage — "Chaos and
# fault-injection tests") requires test coverage for each listed
# failure mode. The deterministic check asserts that tests/fault/
# exists and contains at least one test file whose contents mention
# each scenario (by keyword, because the tests are free to name
# themselves however the author prefers).
fault_dir="tests/fault"
if [[ ! -d "${fault_dir}" ]]; then
  echo "verify-standards: ${fault_dir}/ is missing." >&2
  echo "  Add a fault-injection test layer per" >&2
  echo "  .claude/instructions/testing-standards.md § Coverage." >&2
  exit 1
fi

declare -A fault_scenarios=(
  [sqlite]="SQLite / storage write errors"
  [audit]="audit-log disk-full or unwritable"
  [keyring]="keyring backend unavailable"
  [plugin]="notification plugin timeout / exception"
  [agent_auth]="agent-auth unreachable from things-bridge"
  [applescript]="Things AppleScript subprocess failure"
)

fault_missing=0
for scenario in "${!fault_scenarios[@]}"; do
  # Accept matches in filenames or file contents under tests/fault/.
  if ! { find "${fault_dir}" -type f -name "*.py" -print 2>/dev/null | grep -qi "${scenario}"; } \
    && ! grep -r -l -i "${scenario}" "${fault_dir}" >/dev/null 2>&1; then
    echo "verify-standards: no fault-injection coverage for: ${fault_scenarios[${scenario}]}" >&2
    fault_missing=1
  fi
done

if [[ ${fault_missing} -ne 0 ]]; then
  echo "  Add tests under ${fault_dir}/ (either in a file whose name mentions" >&2
  echo "  the scenario keyword, or referencing the keyword in the test body)." >&2
  exit 1
fi

echo "verify-standards: ${fault_dir}/ covers all required fault-injection scenarios."

# Observability design documentation per
# .claude/instructions/service-design.md ("Observability design") and
# the deterministic regression check from issue #33:
#
#   - Either design/DESIGN.md or design/OBSERVABILITY.md contains the
#     five required pieces: log schema, log levels, log location,
#     retention policy, and metrics catalogue. Heading patterns are
#     forgiving (accept a dedicated heading or a sentence whose text
#     carries the topic) because the content has historically lived
#     inline under ``## Observability`` rather than under a named
#     subheading per topic.

observability_missing=0

fail_observability_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  observability_missing=1
}

observability_sources=()
[[ -f design/DESIGN.md ]] && observability_sources+=(design/DESIGN.md)
[[ -f design/OBSERVABILITY.md ]] && observability_sources+=(design/OBSERVABILITY.md)

if [[ ${#observability_sources[@]} -eq 0 ]]; then
  fail_observability_check \
    "neither design/DESIGN.md nor design/OBSERVABILITY.md exists." \
    "Create one of these documents with the observability design."
else
  observability_text="$(cat "${observability_sources[@]}")"

  # Combined "name|pattern" entries keep the required-topic list
  # sortable without misaligned parallel arrays. Each pattern is a
  # case-insensitive ERE alternation that matches either a section
  # heading or a distinctive phrase from the body copy.
  observability_topics=(
    # keep-sorted start
    "log-levels|^###[[:space:]]+Log levels|log[- ]level policy"
    "log-location|^###[[:space:]]+Log location|log location"
    "log-schema|^###[[:space:]]+Audit log fields|^###[[:space:]]+Log schema|log schema|schema_version"
    "metrics-catalogue|^###[[:space:]]+HTTP server metrics|^###[[:space:]]+Metrics catalogue|metrics catalogue"
    "retention|^###[[:space:]]+Retention|retention (is the operator|policy|expectations)"
    # keep-sorted end
  )

  for entry in "${observability_topics[@]}"; do
    topic_name="${entry%%|*}"
    topic_pattern="${entry#*|}"
    if ! grep -qiE "${topic_pattern}" <<<"${observability_text}"; then
      fail_observability_check \
        "observability design is missing the '${topic_name}' topic." \
        "Add coverage matching: ${topic_pattern}"
    fi
  done
fi

if [[ ${observability_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: observability design (log schema, levels, location, retention, metrics catalogue) is documented."

# ---------------------------------------------------------------------------
# Performance budget.
# ---------------------------------------------------------------------------
# .claude/instructions/testing-standards.md (Performance — "Performance
# budget") requires BOTH a documented latency target for critical
# operations in the design docs AND at least one test asserting that
# budget. The deterministic check asserts:
#
#   1. design/DESIGN.md contains a "Performance budget" heading.
#   2. pyproject.toml registers the `perf_budget` pytest marker.
#   3. At least one test file applies `@pytest.mark.perf_budget`.
design_file="design/DESIGN.md"
if [[ ! -f "${design_file}" ]]; then
  echo "verify-standards: ${design_file} is missing." >&2
  exit 1
fi

if ! grep -qE "^## +Performance budget\b" "${design_file}"; then
  echo "verify-standards: ${design_file} is missing a '## Performance budget' section." >&2
  echo "  Document a latency target per .claude/instructions/testing-standards.md § Performance." >&2
  exit 1
fi

if ! python3 -c "
import sys, tomllib
from pathlib import Path
pyproject = tomllib.loads(Path('pyproject.toml').read_text())
markers = pyproject.get('tool', {}).get('pytest', {}).get('ini_options', {}).get('markers', [])
if not any(str(m).startswith('perf_budget') for m in markers):
    sys.exit('perf_budget marker not registered in [tool.pytest.ini_options].markers')
" 2>/tmp/verify-standards-perf.err; then
  echo "verify-standards: pyproject.toml does not register the perf_budget pytest marker:" >&2
  cat /tmp/verify-standards-perf.err >&2
  rm -f /tmp/verify-standards-perf.err
  exit 1
fi
rm -f /tmp/verify-standards-perf.err

if ! grep -r -l -E "@pytest\\.mark\\.perf_budget\\b" tests/ >/dev/null 2>&1; then
  echo "verify-standards: no test under tests/ applies @pytest.mark.perf_budget." >&2
  echo "  Add a perf-budget-assertion test referencing ${design_file} § Performance budget." >&2
  exit 1
fi

echo "verify-standards: ${design_file} documents a performance budget and at least one test carries the perf_budget marker."

# Rate-limiting / DoS posture per
# .claude/instructions/service-design.md ("Rate limiting / DoS posture")
# and the deterministic regression check from issue #30:
#
#   - design/decisions/ contains an ADR addressing rate limiting / DoS.
#     The gate matches on ADR titles or body copy that carry the
#     "rate limit" keyword so a rename of the current ADR filename
#     still satisfies the check as long as the rationale keeps
#     living in an ADR.

rate_limit_adr_found=0
# Match the ADR title (first ``# ADR`` line), not body-copy mentions —
# ASVS and other cross-cutting ADRs list "rate limiting" in their
# follow-ups without actually carrying the posture decision. Requiring
# the keyword in the title keeps the gate pointed at the dedicated ADR.
for adr in design/decisions/*.md; do
  [[ -f "${adr}" ]] || continue
  base="$(basename "${adr}")"
  [[ "${base}" == "README.md" || "${base}" == "TEMPLATE.md" ]] && continue
  if grep -m1 "^# ADR" "${adr}" \
    | grep -qiE "rate[[:space:]]?limit|DoS posture|denial[- ]of[- ]service"; then
    rate_limit_adr_found=1
    rate_limit_adr="${adr}"
    break
  fi
done

if [[ ${rate_limit_adr_found} -eq 0 ]]; then
  echo "verify-standards: no ADR under design/decisions/ addresses rate limiting / DoS posture." >&2
  echo "  Add an ADR with the decision (implement with thresholds, or defer with rationale)." >&2
  exit 1
fi

echo "verify-standards: rate-limiting / DoS posture is recorded in ${rate_limit_adr}."

# Key-loss / recovery design per
# .claude/instructions/service-design.md ("Key recovery and loss
# scenarios") and the deterministic regression check from issue #31:
#
#   - design/DESIGN.md contains a documented "Key loss and recovery"
#     section. A missing section would silently leave the project
#     without a documented behaviour for the keyring-wiped-but-DB-
#     persists scenario.

if ! grep -qE "^## +Key loss and recovery\b" design/DESIGN.md; then
  echo "verify-standards: design/DESIGN.md is missing a '## Key loss and recovery' section." >&2
  echo "  Document detection, user warning, and recovery behaviour per" >&2
  echo "  .claude/instructions/service-design.md § Key recovery and loss scenarios." >&2
  exit 1
fi

echo "verify-standards: design/DESIGN.md documents key-loss detection and recovery."

# DB schema migration system per
# .claude/instructions/service-design.md ("DB schema migration strategy")
# and the deterministic regression check from issue #29:
#
#   1. src/agent_auth/store.py contains no CREATE TABLE / ALTER TABLE —
#      schema DDL lives exclusively in
#      src/agent_auth/migrations/_catalogue.py and cannot drift from
#      application code.
#   2. At least one migration is declared in the catalogue (so the
#      runner has something to apply) and the catalogue ships a
#      reversible v=1 entry.
#   3. Running the catalogue against an empty DB and then rolling back
#      leaves the tracking table empty again ("up/down" drift check —
#      the hand-rolled analogue of ``alembic check``).

migrations_drift="$(
  python3 - <<'PY'
import pathlib
import re
import sqlite3
import sys
import tempfile

errors: list[str] = []

store_src = pathlib.Path("src/agent_auth/store.py").read_text()
if re.search(r"\b(CREATE|ALTER)\s+TABLE\b", store_src, re.IGNORECASE):
    errors.append(
        "src/agent_auth/store.py contains CREATE TABLE / ALTER TABLE — "
        "all schema DDL must live in src/agent_auth/migrations/_catalogue.py"
    )

catalogue_path = pathlib.Path("src/agent_auth/migrations/_catalogue.py")
if not catalogue_path.is_file():
    errors.append("src/agent_auth/migrations/_catalogue.py is missing")
else:
    sys.path.insert(0, "src")
    from agent_auth.migrations import migrate_down, migrate_up
    from agent_auth.migrations._catalogue import CATALOGUE

    if not CATALOGUE:
        errors.append(
            "CATALOGUE in _catalogue.py is empty — declare at least the initial migration"
        )
    else:
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp) / "drift.db"
            conn = sqlite3.connect(db)
            try:
                conn.execute("PRAGMA foreign_keys=ON")
                applied = migrate_up(conn)
                if [m.version for m in applied] != [m.version for m in CATALOGUE]:
                    errors.append(
                        "migrate_up did not apply every declared migration against an empty DB"
                    )
                reverted = migrate_down(conn, to_version=0)
                if {m.version for m in reverted} != {m.version for m in CATALOGUE}:
                    errors.append(
                        "migrate_down did not revert every applied migration back to version 0"
                    )
                remaining = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name != 'schema_migrations'"
                ).fetchall()
                if remaining:
                    names = ", ".join(r[0] for r in remaining)
                    errors.append(f"migrate_down left stray tables: {names}")
            finally:
                conn.close()

for err in errors:
    print(err)
if errors:
    sys.exit(1)
PY
)" || {
  echo "verify-standards: migration system drift detected:" >&2
  while IFS= read -r line; do
    echo "  - ${line}" >&2
  done <<<"${migrations_drift}"
  exit 1
}

echo "verify-standards: schema DDL lives in migrations/_catalogue.py; up/down drift check passes."

# Notification plugin trust boundary per
# .claude/instructions/service-design.md ("Plugin trust boundary") and
# the deterministic regression check from issue #6:
#
#   1. src/agent_auth/server.py must not call importlib.import_module —
#      the pre-#6 in-process plugin loader is gone for good, and
#      re-introducing it widens the trust boundary to every plugin
#      author. strip_comments guards against a stale mention
#      satisfying the grep after the real call has been removed.
#   2. src/agent_auth/config.py must declare notification_plugin_url
#      (the URL-based field) — a revert of the schema to the old
#      notification_plugin / notification_plugin_config module-name
#      pair would silently re-enable in-process loading on the next
#      loader change.

notifier_drift=0
server_stripped="$(strip_comments src/agent_auth/server.py)"
if grep -qE "\\bimportlib\\.import_module\\b" <<<"${server_stripped}"; then
  echo "verify-standards: src/agent_auth/server.py calls importlib.import_module." >&2
  echo "  Notification plugins must be out-of-process HTTP endpoints (see #6 and" >&2
  echo "  design/DESIGN.md § Notification plugin wire protocol)." >&2
  notifier_drift=1
fi

config_stripped="$(strip_comments src/agent_auth/config.py)"
if ! grep -qE "\\bnotification_plugin_url\\b" <<<"${config_stripped}"; then
  echo "verify-standards: src/agent_auth/config.py is missing 'notification_plugin_url'." >&2
  echo "  The notifier is a URL, not a Python module path — see #6." >&2
  notifier_drift=1
fi
if grep -qE "\\bnotification_plugin[[:space:]]*:" <<<"${config_stripped}"; then
  echo "verify-standards: src/agent_auth/config.py still declares the legacy 'notification_plugin:' module-name field." >&2
  echo "  Replace with 'notification_plugin_url: str = \"\"'." >&2
  notifier_drift=1
fi

if [[ ${notifier_drift} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: notification plugin is URL-based (out-of-process); no importlib.import_module in server.py."

# ---------------------------------------------------------------------------
# Benchmark suite with scheduled CI workflow.
# ---------------------------------------------------------------------------
# .claude/instructions/testing-standards.md (Performance — "Benchmark
# suite") requires a maintained benchmark suite that runs in CI on a
# schedule. The deterministic regression check asserts both sides
# cannot silently drift apart:
#
#   1. benchmarks/ exists and contains at least one test_*.py file,
#      so deleting the benchmarks but leaving the workflow behind
#      fails the gate.
#   2. .github/workflows/benchmark.yml exists, has an `on:` block
#      containing a `schedule:` trigger, and its steps invoke either
#      `task benchmark` or a direct pytest run against benchmarks/,
#      so deleting the workflow (or accidentally narrowing it to
#      workflow_dispatch-only) fails the gate.

benchmark_missing=0

fail_benchmark_check() {
  echo "verify-standards: $1" >&2
  echo "  $2" >&2
  benchmark_missing=1
}

benchmarks_dir="benchmarks"
if [[ ! -d "${benchmarks_dir}" ]]; then
  fail_benchmark_check \
    "${benchmarks_dir}/ directory is missing." \
    "Add a pytest-benchmark suite per .claude/instructions/testing-standards.md § Performance."
else
  # Accept any test_*.py under benchmarks/ so authors are free to
  # split the suite across files. compgen keeps the shell-glob match
  # compatible with `set -u`.
  if ! compgen -G "${benchmarks_dir}/test_*.py" >/dev/null; then
    fail_benchmark_check \
      "${benchmarks_dir}/ contains no test_*.py benchmark files." \
      "Add at least one pytest-benchmark test file (see benchmarks/README.md)."
  fi
fi

benchmark_workflow=".github/workflows/benchmark.yml"
if [[ ! -f "${benchmark_workflow}" ]]; then
  fail_benchmark_check \
    "${benchmark_workflow} is missing." \
    "Add a scheduled GitHub Actions workflow that runs the benchmark suite."
else
  # Match ``on:`` and ``schedule:`` inside it. Allow either the
  # short form (``on: [schedule]``) or the mapping form
  # (``on:\n  schedule:``). Strip comments so a disabled sample
  # does not satisfy the gate.
  workflow_stripped="$(sed -E 's/(^|[[:space:]])#.*$//' "${benchmark_workflow}")"
  if ! grep -qE "^on:" <<<"${workflow_stripped}"; then
    fail_benchmark_check \
      "${benchmark_workflow} has no 'on:' trigger block." \
      "Add 'on:' with a 'schedule:' entry."
  elif ! grep -qE "^[[:space:]]*schedule:" <<<"${workflow_stripped}"; then
    fail_benchmark_check \
      "${benchmark_workflow} does not trigger on 'schedule:'." \
      "Add a 'schedule:' cron entry inside the 'on:' block."
  fi

  # The workflow must actually invoke the benchmark suite — accept
  # either the ``task benchmark`` wrapper or a raw ``pytest
  # benchmarks/`` invocation, so the gate does not mandate the
  # Taskfile indirection specifically.
  if ! grep -qE "task[[:space:]]+benchmark\b|pytest[[:space:]].*benchmarks/" <<<"${workflow_stripped}"; then
    fail_benchmark_check \
      "${benchmark_workflow} does not invoke the benchmark suite." \
      "Call 'task benchmark' or run pytest against 'benchmarks/' in the workflow steps."
  fi
fi

if [[ ${benchmark_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: benchmark suite exists under ${benchmarks_dir}/ and ${benchmark_workflow} runs it on a schedule."
