#!/usr/bin/env bash

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

  if ! grep -qE "\\b${tool}\\b" <<<"${lefthook_stripped}"; then
    fail_bash_check "${tool}" "lefthook.yml" \
      "Add a pre-commit command that invokes '${tool}' to lefthook.yml."
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

# CHANGELOG.md must exist and contain a ## [Unreleased] section per
# .claude/instructions/release-and-hygiene.md (Keep-a-Changelog format).

if [[ ! -f CHANGELOG.md ]]; then
  echo "verify-standards: CHANGELOG.md is missing from the repo root." >&2
  echo "  Add CHANGELOG.md following the Keep-a-Changelog format." >&2
  exit 1
fi

if ! grep -qE "^## \\[Unreleased\\]" CHANGELOG.md; then
  echo "verify-standards: CHANGELOG.md does not contain a '## [Unreleased]' section." >&2
  echo "  Add '## [Unreleased]' as the topmost version section in CHANGELOG.md." >&2
  exit 1
fi

echo "verify-standards: CHANGELOG.md exists with a [Unreleased] section."

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
  security_section_names=(
    # keep-sorted start
    audit-surface
    cybersecurity-standard
    key-handling
    revocation-flow
    threat-model
    trust-boundaries
    vulnerability-reporting
    # keep-sorted end
  )
  security_section_patterns=(
    "## Audit surface|## Audit log"
    "## Cybersecurity standard|Cybersecurity standard"
    "## Key handling"
    "## Revocation flow"
    "## Threat model"
    "## Trust boundaries|## Trust boundary"
    "## Vulnerability reporting|## Reporting vulnerabilities"
  )

  [[ ${#security_section_names[@]} -eq ${#security_section_patterns[@]} ]] \
    || {
      echo "BUG: security parallel arrays length mismatch" >&2
      exit 1
    }

  for i in "${!security_section_names[@]}"; do
    if ! grep -qiE "${security_section_patterns[${i}]}" SECURITY.md; then
      fail_security_check \
        "SECURITY.md is missing a '${security_section_names[${i}]}' section." \
        "Add a section matching: ${security_section_patterns[${i}]}"
    fi
  done
fi

if [[ ${security_missing} -ne 0 ]]; then
  exit 1
fi

echo "verify-standards: SECURITY.md exists with all required sections including the cybersecurity standard."

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

# GitHub repository About metadata must be populated per
# .claude/instructions/release-and-hygiene.md. Skipped when 'gh' is not
# available or not authenticated (e.g. local dev without credentials).

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  repo_meta="$(gh repo view --json description,homepageUrl,repositoryTopics 2>/dev/null || true)"
  if [[ -n "${repo_meta}" ]]; then
    mapfile -t _gh_fields < <(
      python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print(d.get('description', ''))
print(d.get('homepageUrl', ''))
print(len(d.get('repositoryTopics', [])))
" "${repo_meta}"
    )
    repo_description="${_gh_fields[0]:-}"
    repo_homepage="${_gh_fields[1]:-}"
    repo_topics="${_gh_fields[2]:-0}"

    gh_meta_missing=0
    if [[ -z "${repo_description}" ]]; then
      echo "verify-standards: GitHub repo 'About' description is empty." >&2
      echo "  Set it via 'gh repo edit --description \"...\"'." >&2
      gh_meta_missing=1
    fi
    if [[ -z "${repo_homepage}" ]]; then
      echo "verify-standards: GitHub repo 'About' homepage is empty." >&2
      echo "  Set it via 'gh repo edit --homepage \"...\"'." >&2
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
    echo "verify-standards: GitHub repo About metadata (description, homepage, topics) is populated."
  fi
else
  echo "verify-standards: 'gh' not available or not authenticated; skipping GitHub metadata check."
fi
