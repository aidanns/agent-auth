<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan — kebab-case workflow names + flat aggregator (issue #556)

## Context and scope

Three pieces of CI naming / structure debt in one PR:

1. **Naming drift** — workflow filenames are kebab-case, but workflow `name:`
   fields are Title Case (`Merge Bot`, `OpenSSF Scorecard`), composite-action
   `name:` fields are Sentence case (`Setup toolchain`), and job-level
   `name:` is mixed. Each rename forces coordinated edits at every
   case-sensitive consumer.
2. **Aggregator drift from #440** — five `required-checks-passed`
   aggregators exist (`ci.yml`, `check-fmt.yml`, `check-lint.yml`,
   `check-security.yml`, `nightly.yml`, `weekly.yml`); the locked-in
   #440 decision was a single repo-wide aggregator at `ci.yml`.
3. **Verbose workflow comments** — multi-paragraph migration prose
   ("Strategy C", "Phase 5", "issue #440 Phase 2") that's now obvious
   from structure.

Side effects:

- `merge-bot.yml` `workflow_run.workflows: [CI]` → `[ci]` after the
  parent `name:` flips.
- `scripts/ci/diff-dependent-jobs.sh` hardcoded case statement → dynamic
  `yq`-driven leaf enumeration that walks `ci.yml`'s
  `required-checks-passed.needs:` and reads each child's `jobs:` keys.
- `tests/test_ci_diff_dependent_probe.py` golden-leaf set updates.
- `scripts/verify-standards.sh` gains `workflow.name == filename` and
  `action.name == directory` assertions.
- `.claude/instructions/tooling-and-ci.md` "Naming conventions" section
  rewritten.
- New ADR — next free number is **0046**, not 0045 (the issue body
  predates ADR 0045 — Claude co-authorship trailer — landing on main).

Branch-protection coordination: the required check name changes from
`CI / Required checks passed` to `ci / required-checks-passed`. The
ruleset swap happens at merge time (orchestrator-owned, single brief
unprotected window) — outside this PR's scope.

## Design and verification

- **Verify implementation against design doc** — N/A. No design-doc
  surface for the workflow-naming rule; the standard lives in
  `.claude/instructions/tooling-and-ci.md`, which this PR rewrites.
- **Threat model** — N/A. No security-relevant change. Aggregator-
  flattening reduces job count but preserves the `skipped → failure`
  contract (#441) and the verified-prior-success carve-out (#527).
- **Post-incident review** — N/A. No vulnerability remediation.
- **Architecture Decision Records** — write
  `design/decisions/0046-flat-required-checks-aggregator-and-kebab-case-workflow-names.md`.
  Captures (a) workflow / action `name:` = filename / directory,
  (b) job `name:` field dropped for non-matrix jobs, (c) step `name:`
  Title Case prose, (d) one repo-wide `required-checks-passed`
  aggregator. References #414 (partial supersession of the naming rule)
  and #440 (restoration of the aggregator decision).
- **Cybersecurity standard compliance** — N/A. No new security
  controls. The aggregator's `skipped = failure` strict contract (#441)
  and the verified-prior-success carve-out (#527) are preserved
  byte-for-byte; the only structural change is removing redundant
  intermediate aggregators.
- **QM / SIL compliance** — N/A. CI-tooling change, no functional
  surface.

## Implementation

### Phase 1 — naming sweep (mechanical)

For each workflow file `.github/workflows/<filename>.yml`:

- Set top-level `name: <filename>` (e.g. `merge-bot`, `ci`,
  `open-ssf-scorecard`).
- Drop `name:` on every non-matrix job (the job ID becomes the
  rendered display name). Matrix jobs keep their parens-template
  name (e.g. `unit-tests (${{ matrix.package }})`).

For each composite action `.github/actions/<dir>/action.yml`:

- Set top-level `name: <dir>` (e.g. `setup-toolchain`,
  `install-pr-lint-validator`, `read-required-contexts`,
  `build-integration-test-image`).

Step `name:` fields: leave as-is unless they read awkwardly under the
new "Title Case prose" rule. The repo currently uses Sentence-case
imperatives uniformly; touching every step is high-churn and
out-of-scope for this PR. The rule is forward-looking — new step
names follow Title Case prose; existing ones stay (the standards
review will not flag them).

### Phase 2 — drop intermediate aggregators

Drop `required-checks-passed` from:

- `check-fmt.yml`
- `check-lint.yml`
- `check-security.yml`
- `nightly.yml`
- `weekly.yml`

In `ci.yml`'s `required-checks-passed.needs:`, replace the parent
job IDs of the three children that previously aggregated their own
internal jobs with the **flattened set of those children's jobs**.
Specifically:

- `check-fmt` was a parent over (`spdx-license-headers`, `treefmt`,
  `ruff-format`) → expand to those three direct children.
- `check-lint` was a parent over (`python`, `systems-engineering`)
  → expand.
- `check-security` was a parent over (`codeql-analyse`, `ripsecrets`,
  `check-dependency-review`, `check-dependency-submission`) → expand.

This means `ci.yml` calls those workflows directly rather than through
intermediate orchestrators. **Decision:** keep the intermediate
orchestrator files (`check-fmt.yml`, `check-lint.yml`,
`check-security.yml`) but strip them down to no-op shells? Or delete
them entirely and call the leaves direct from `ci.yml`?

Per the issue body: **drop the aggregator job from the intermediate
orchestrators**. The orchestrators themselves stay — they provide the
permissions-union and `workflow_call` shape for their children. The
removal is just the `required-checks-passed:` job inside each
intermediate file. The parent `ci.yml`'s `needs:` continues to
reference the orchestrator job IDs (`check-fmt`, `check-lint`,
`check-security`); GitHub's `needs:` on a `workflow_call` job
collapses every internal job's result into a single `success` /
`failure`, so dropping the intermediate aggregator job inside the
called workflow does not change the semantics seen from `ci.yml`.

In `ci.yml`'s `required-checks-passed`, drop the
`name: Required checks passed` field so the rendered check-run name
becomes `ci / required-checks-passed` (kebab-case by job ID).

### Phase 3 — rework `scripts/ci/diff-dependent-jobs.sh`

Replace the hardcoded `case "${jid}"` statement with dynamic yq-driven
enumeration:

1. Read `ci.yml`'s `required-checks-passed.needs:` array.
2. For each surviving job ID (after subtracting `plan` and the
   metadata-dependent set), read the corresponding workflow_call file
   `.github/workflows/<jid>.yml` (resolved by reading the parent's
   `jobs.<jid>.uses:` field).
3. From that child file, enumerate `jobs:` keys, filtering out any
   that are themselves `required-checks-passed` (none should remain
   after Phase 2; the filter is defence-in-depth).
4. For each child job, recursively expand if `uses:` points at another
   workflow_call file.
5. For matrix jobs, read the `matrix:` block and expand rows into
   parens-variant names following the existing `name: <prefix> (${{ matrix.<key> }})` convention.
6. Emit each leaf as `<parent-orch-job-id> / <leaf-job-id-or-name>`.

The leaf naming convention remains: `<parent-job-id>/<leaf-display>`,
where the leaf display is the matrix-template name when present, else
the job ID.

### Phase 4 — update `merge-bot.yml`

Change `workflow_run.workflows: [CI]` to `[ci]`. Update inline
comments that reference `CI` as a name (e.g. "single workflow `CI`")
to reference `ci` lowercase.

Update `tests/test_merge_bot_workflow_run_trigger.py`'s
`EXPECTED_WORKFLOWS` frozenset to `{"ci"}` (currently stale —
contains pre-#467 names that no longer exist; this PR fixes it as
side-effect cleanup since the merge-bot workflow_run set is being
edited anyway).

### Phase 5 — comment cleanup

Sweep workflow file headers and inline comments. Remove migration-
phase prose (`#440 Phase 5`, `Strategy C`, `until ... retires the original`, `#414 naming convention`); trim multi-paragraph rationale
to one-line "non-obvious why" notes. Keep comments documenting real
surprises:

- `skipped = failure` rationale (#441).
- Verified-prior-success carve-out (#527).
- Fork-PR `GITHUB_TOKEN` short-circuits.
- Anti-recursion / `workflow_run` from `GITHUB_TOKEN` rule
  (`merge-bot.yml` § "Listen on `ci` only").
- SLSA `@vX` exception in `setup-toolchain/action.yml`.

### Phase 6 — extend `scripts/verify-standards.sh`

Add a check that for every `.github/workflows/<filename>.yml` the
top-level `name:` equals `<filename>` (filename minus `.yml`); for
every `.github/actions/<dir>/action.yml` the top-level `name:` equals
`<dir>`.

Run on `yq -r '.name'` reads; fail-closed if `name:` is missing or
mismatched.

### Phase 7 — rewrite `tooling-and-ci.md`

Replace the "Naming conventions" section verbatim:

- Workflow `name:` = filename minus `.yml` (kebab-case).
- Action `name:` = directory name (kebab-case).
- Job `name:` field dropped for non-matrix jobs (fall back to job
  ID); matrix jobs use the parens template.
- Step `name:` = Title Case prose.

Adjust the "Single Required checks passed aggregator" section to
reflect the flat structure: one repo-wide aggregator at `ci.yml`,
referenced by branch protection as `ci / required-checks-passed`.
Remove the "Per-child aggregators" subsection (no per-child
aggregators any more).

### Phase 8 — write ADR 0046

Use `design/decisions/TEMPLATE.md`. Capture:

- The naming rule (workflow `name:` = filename, action `name:` =
  directory, job `name:` dropped on non-matrix, step `name:` Title
  Case prose).
- The aggregator restoration to one repo-wide aggregator.
- Reference #414 (partial supersession of the original naming
  standard) and #440 (restoration of the locked-in aggregator
  decision).

## Post-implementation standards review

- **Coding standards** — N/A. CI/YAML changes only; no Python source
  edits.
- **Service design** — N/A. No service surface change.
- **Release and hygiene** — verify no required project file regresses
  (CONTRIBUTING.md, CHANGELOG.md, LICENSE, SECURITY.md). The PR is
  CI-only; none of these surfaces should change.
- **Testing standards** — verify the diff-dependent probe test
  (`tests/test_ci_diff_dependent_probe.py`) still pins the
  diff-dependent set correctly after the helper-script rework.
- **Tooling and CI standards** — verify `task verify-standards`
  passes; this PR's own naming-rule additions to verify-standards.sh
  are part of the standards check.

## Test plan

- `task verify-standards` — must pass with the new workflow-name and
  action-name assertions in place.
- `task lint` — bash + yaml lint against changed workflows /
  scripts.
- `pytest tests/test_ci_diff_dependent_probe.py -v` — exercises the
  diff-dependent helper end-to-end (matrix expansion, recursion, leaf
  set).
- `pytest tests/test_merge_bot_workflow_run_trigger.py -v` —
  exercises the merge-bot trigger contract; passes after the
  EXPECTED_WORKFLOWS update.
- Visual diff of the rendered check-run names — `gh pr checks <pr>`
  on the PR itself should show `ci / required-checks-passed` as the
  aggregator's check-run name once the orchestrator flips branch
  protection at merge time.

## Out of scope (handled at merge time, not in this PR)

- Branch-protection ruleset edit (orchestrator-owned coordination).
- Step `name:` Title Case sweep across every workflow file (forward-
  looking rule; the standards review will not retroactively flag
  existing Sentence-case step names).
