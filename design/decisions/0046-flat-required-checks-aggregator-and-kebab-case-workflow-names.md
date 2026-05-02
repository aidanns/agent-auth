<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0046 — Flat `required-checks-passed` aggregator and kebab-case workflow / action names

## Status

Accepted — 2026-05-02. Partially supersedes the naming sub-section of
the standard recorded under issues #414 and #470 in
`.claude/instructions/tooling-and-ci.md`. Restores the locked-in
single-aggregator decision from #440 that drifted as intermediate
orchestrators each grew their own `required-checks-passed` job.

## Context

Two pieces of CI infrastructure debt accumulated under issues #414 and
#440 and were collapsed into a single PR (#556).

### Naming drift across three orthographies

The previous standard used three different naming styles for what is
conceptually the same artefact:

- Workflow filename: kebab-case (`merge-bot.yml`).
- Workflow `name:` field: Title Case with preserved acronym caps
  (`Merge Bot`, `OpenSSF Scorecard`, `SPDX License Headers`).
- Job IDs: kebab-case (`merge-bot`).

Composite-action `name:` fields used Sentence case ("Setup
toolchain"). Job-level `name:` fields drifted between Sentence case
("Plan"), Title Case ("Required checks passed"), and kebab-case
restating the job ID ("check-fmt").

Each rename of a workflow `name:` field forced a coordinated edit
at every consumer that named it case-sensitively:

- `merge-bot.yml`'s `workflow_run.workflows: [CI]` listener.
- `scripts/ci/diff-dependent-jobs.sh`'s hardcoded check-run names.
- The branch-protection ruleset's required-status-check entries.
- `tests/test_ci_diff_dependent_*` golden expectations.
- Inline comments scattered across workflow files.

Three orthographies for one artefact created pointless coordination
work — collapsing to one form (`name:` = filename) eliminates an
entire class of drift.

### `required-checks-passed` aggregator drift from #440

Issue #440 locked in:

> One repo-wide `required-checks-passed` aggregator at the top of
> `ci.yml` (no per-workflow aggregators).

The tree drifted to five aggregators (`ci.yml`, `check-fmt.yml`,
`check-lint.yml`, `check-security.yml`, `check-pull-request.yml`,
`nightly.yml`, `weekly.yml`). Each intermediate aggregator is a
runtime job that starts an `ubuntu-latest` runner just to run a
five-line `jq` invocation; GitHub already collapses a workflow_call
child's overall result into `needs.<child>.result` for the calling
workflow, so the intermediate aggregators add a redundant
runner-startup tax without changing the gate semantics.

## Considered alternatives

### Keep the existing Title Case standard

Half the PR scope, no branch-protection coordination, but leaves the
three-orthography drift unfixed.

**Rejected** because:

- The same coordination work would reappear next time someone
  renames a workflow `name:` field.
- The "preserve canonical capitalisation for acronyms" rule
  requires per-acronym judgement (`CI`, `DCO`, `PR`, `CodeQL`,
  `OpenSSF`, `SPDX` — all subjective). A mechanical "filename =
  `name:`" rule has zero judgement calls and zero drift surface.

### Keep the per-workflow aggregators in the three nesting children

Keep `required-checks-passed` jobs in `check-fmt.yml`,
`check-lint.yml`, `check-security.yml` so
`scripts/ci/diff-dependent-jobs.sh`'s case statement stays short.

**Rejected** because:

- The script is reworked dynamically (yq-driven leaf enumeration)
  in the same PR, so the case-statement-length argument no longer
  applies.
- Each kept aggregator costs an extra `ubuntu-latest` job startup
  per CI run; the runtime cost is real, the structural payoff is
  zero (`needs.<child>.result` already collapses the child's
  outcome).

### Two-stage PR — aggregator removal first, then naming

Cleaner from a merge-blast-radius perspective.

**Rejected** because:

- It doubles the docs / comments / `verify-standards.sh` churn —
  every section that names an aggregator or a workflow has to be
  edited twice.
- Bundling is acceptable given the planned merge-time
  branch-protection coordination window for the rename half.

## Decision

The new naming rule is mechanical: an artefact's `name:` is its own
filename / directory name.

| Surface                        | Rule                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Workflow `name:` field         | Equal to filename minus `.yml` (kebab-case). `merge-bot.yml` reads `name: merge-bot`.                                                                               |
| Composite-action `name:` field | Equal to directory name under `.github/actions/` (kebab-case). `setup-toolchain/action.yml` reads `name: setup-toolchain`.                                          |
| Job `name:` field (non-matrix) | **Drop the field.** GitHub falls back to the job ID, which is already kebab-case and what branch protection sees.                                                   |
| Job `name:` field (matrix)     | Parens template: `unit-tests (${{ matrix.package }})`. Each matrix row publishes a stable, distinct check-run.                                                      |
| Step `name:` field             | Title Case prose; acronyms / tool names / proper nouns stand in their natural form. Forward-looking — existing Sentence-case names are not retroactively rewritten. |

`scripts/verify-standards.sh` enforces the workflow / action `name:`
rules as canaries.

The aggregator rule restores the #440 lock-in: **one repo-wide
`required-checks-passed` aggregator at `ci.yml`**, with no
intermediate aggregators in any other orchestrator. Branch
protection on `main` references only `ci / required-checks-passed`.

`scripts/ci/diff-dependent-jobs.sh` is reworked from a hand-edited
`case` statement to dynamic `yq`-driven leaf enumeration — it reads
`ci.yml`'s `required-checks-passed.needs:`, walks each child's
`uses:` workflow file, recurses through nested workflow_call hops,
and expands matrix rows. New children automatically extend the
probe set without a script edit.

## Consequences

### Positive

- One mechanical naming rule eliminates per-acronym judgement calls
  and the coordinated-rename tax that came with case-sensitive
  consumers of workflow `name:` fields.
- Five fewer `required-checks-passed` aggregator jobs per CI run
  (intermediate orchestrators no longer spin up an extra
  `ubuntu-latest` runner each).
- The diff-dependent helper is now derived from the workflow files
  themselves rather than a hand-edited table — adding a new child
  to `ci.yml` no longer needs a sibling helper edit.
- `scripts/verify-standards.sh` catches naming drift at PR time.

### Negative

- Branch-protection coordination at merge time: the required check
  name changes from `CI / Required checks passed` to
  `ci / required-checks-passed`. Brief unprotected window during
  the ruleset swap.
- Step `name:` Title Case rule applies forward only; the existing
  Sentence-case step names across the tree are not rewritten in
  this PR. Future contributors will see mixed casing until natural
  edits sweep through.
- `merge-bot.yml`'s `workflow_run.workflows: [ci]` listener is
  case-sensitive against the workflow `name:` field — a future
  rename of `ci.yml` to a new filename would need a coordinated
  update here too. The mechanical rule keeps the coordination
  surface small (one entry, in one file), but does not eliminate
  it for the orchestrator workflow itself.

### Affected surfaces

- Every workflow under `.github/workflows/` (~30 files): top-level
  `name:` rewritten, non-matrix job-level `name:` fields dropped,
  five intermediate `required-checks-passed` jobs removed, header
  comments trimmed of migration-phase prose.
- Both composite actions under `.github/actions/`: top-level
  `name:` rewritten to match directory name.
- `scripts/ci/diff-dependent-jobs.sh`: hardcoded case statement
  replaced with dynamic `yq` walk.
- `tests/test_ci_diff_dependent_probe.py`: golden leaf set updated
  to the new flat-aggregator shape.
- `tests/test_merge_bot_workflow_run_trigger.py`: `EXPECTED_WORKFLOWS`
  collapsed to the single `ci` entry (was already stale on `main`
  from before #467).
- `scripts/verify-standards.sh`: new naming canary asserting
  `workflow.name == filename` and `action.name == directory`.
- `.claude/instructions/tooling-and-ci.md`: naming and aggregator
  sections rewritten to match the new rule.
- `.github/workflows/merge-bot.yml`: `workflow_run.workflows: [CI]`
  → `[ci]`.

### Migration mechanics

Single PR, with a coordinated branch-protection swap at merge time:

1. Open the PR. CI runs and produces `ci / required-checks-passed`
   on the PR head. Branch protection still requires the old name,
   so the PR shows as blocked.
2. Right before merge (when no other PRs are queued): edit the
   branch-protection ruleset on `main`, replacing the required
   check `CI / Required checks passed` with
   `ci / required-checks-passed`.
3. The PR's existing CI run satisfies the new requirement — merge.
4. Verify a follow-up PR finds the new required check working.

## Follow-ups

None tracked.
