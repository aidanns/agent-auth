<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Changelog YAML Schema + CI Lint (#295)

Closes #295. Sub-issue of #289 (clean PR-to-commit + release flow).

## Summary

Introduce a file-per-change YAML schema under `changelog/@unreleased/`
that future PRs author and the upcoming release workflow consumes.
Land the supporting building blocks now so dependent sub-issues
(#296 release workflow, #297 CLI helper, #298 bot-mediated authoring)
have a stable surface to bind against:

1. A shared `version_logic` library — bump table, version inference,
   and `release-as` validation. Co-owned by the lint here and by the
   release workflow in #296.
2. A CI lint that runs on every PR (`pull_request: opened, synchronize`)
   and enforces file presence, naming, schema validity, type validity,
   packages validity, and the `release-as` invariant. Documented in
   the PR body so the maintainer can register it as a required check
   on the `main` ruleset post-merge.
3. The empty `changelog/@unreleased/` directory (`.gitkeep`).
4. A short CONTRIBUTING.md section on hand-authoring the YAML.

## Out of scope (deferred to other sub-issues)

- The release workflow that consumes the YAML (#296).
- The `task changelog-add` CLI helper (#297).
- Bot-mediated authoring via `==CHANGELOG_MSG==` markers (#298).
- Decommissioning `@semantic-release/*` and `.releaserc.mjs` (handled
  by #296 once the release workflow lands).

## Design verification

No new ADR — this PR implements the schema decided in #289's design
section and the type → bump mapping spelled out in the issue body.
The ADR for the overall flow lives with the umbrella issue (#289)
and the ADR for the release-workflow plumbing belongs to #296.

Decisions captured here:

- **Schema versioning** — defer the Palantir `.v2.yml` filename
  suffix until a real schema break appears. Single-version schema
  for now; future migration writes a sibling `.v2.yml` and a
  migrator. Recorded in the issue.
- **`packages:` field** — parsed and validated against the workspace
  member set, but not yet load-bearing. Single-train versioning
  means every entry contributes to one workspace-level bump.
  Capturing the field now avoids a schema migration when #275
  graduates to per-package release trains.
- **`scripts/changelog/version_logic.py` over a workspace package** —
  the issue suggests "or similar" and explicitly prefers a script
  if there's no other consumer in `packages/`. The release workflow
  (#296) and the CLI helper (#297) will both invoke it; both run
  outside the per-package src/test boundary; promoting it to a full
  workspace package would force a `[project]` block, version pin,
  and dep-graph entry for what is essentially a tooling library.
  Live under `scripts/changelog/` with its own `tests/` tree, mirroring
  the existing `scripts/verify_workspace_deps.py` precedent.
- **PyYAML availability** — already pulled in transitively via the
  workspace lockfile; the lint can `import yaml`. No new dependency
  needed.

## Implementation

### `scripts/changelog/`

```text
scripts/changelog/
  __init__.py
  version_logic.py
  lint.py
  tests/
    __init__.py
    conftest.py
    test_version_logic.py
    test_lint.py
```

- `version_logic.py` — public API:
  - `BumpType` enum: `MAJOR | MINOR | PATCH | NONE`.
  - `EntryType` enum (the six allowed values).
  - `ChangelogEntry` dataclass with `entry_type`, `description`,
    `links`, `packages`, `release_as`, plus a `source_path` for
    error provenance.
  - `parse_entry_file(path: Path) -> ChangelogEntry` — reads, parses,
    and validates a single YAML file. Raises `ChangelogValidationError`
    with `path` + `field` + reason on any deviation.
  - `bump_for(entry_type: EntryType, current_version: Version) -> BumpType`
    — single source of truth for the bump table.
  - `infer_next_version(current_version: str, entries: list[ChangelogEntry]) -> str`
    — applies the largest implied bump; respects the demote-to-minor
    rule when `current_version` is in the 0.x range.
  - `validate_release_as(entries: list[ChangelogEntry], current_version: str) -> None`
    — raises on conflicting `release-as` values across files; raises
    when a `release-as` is `<= infer_next_version(...)` ignoring overrides.
  - Module docstring documents the public API for downstream callers.
- `lint.py` — CLI driver invoked from the GitHub Action. Reads the
  PR number, head SHA, base SHA from env (or argv), enumerates added
  files via `git diff --name-only --diff-filter=A <base>...<head>`,
  applies the four checks from the issue, and exits non-zero with a
  human-readable error per failure (path + field + reason).

### `changelog/@unreleased/.gitkeep`

Empty file with no SPDX header (its function is to materialise the
directory; the surrounding REUSE annotation block carries the
licensing override). REUSE.toml gets an entry covering
`changelog/@unreleased/.gitkeep`.

### `.github/workflows/changelog-lint.yml`

`pull_request: types: [opened, synchronize, reopened]` (mirrors the
DCO workflow's trigger set). Single job:

- Checks out the PR head with `fetch-depth: 0` so `git diff` against
  `base.sha` resolves.
- Sets up Python (uses the project's setup-toolchain composite action
  for consistency, even though only `python3` + the stdlib + `yaml`
  are needed; `pyyaml` is already present via the workspace venv).
- Runs `python scripts/changelog/lint.py` with PR metadata in env
  vars: `PR_NUMBER`, `PR_LABELS`, `BASE_SHA`, `HEAD_SHA`.
- Fails with annotations on any error.

The label-based bypass: if the PR carries `no changelog`, the file
presence check is skipped but schema validation still runs over any
files that *are* present (so an opt-out PR can't sneak in malformed
YAML).

### CONTRIBUTING.md

New section under "Commit conventions" titled
"Changelog entries (`changelog/@unreleased/*.yml`)" covering:

- The schema with a worked example.
- The six `type:` values and what each means.
- When to use `packages:` and when to omit it.
- When to use `release-as:` and when not to.
- The `no changelog` label opt-out.
- Pointer that #297 will add a `task changelog-add` helper.

### Not changing yet

- `.releaserc.mjs` keeps its `releaseRules`. The new `version_logic`
  library mirrors the table independently — this PR doesn't touch
  the existing release workflow. #296 retires `@semantic-release/*`
  and `.releaserc.mjs` together.
- No new task in `Taskfile.yml` for the lint itself — it runs in CI
  off `pull_request:` events. The `version_logic` module is callable
  via `python -m scripts.changelog.lint` from the worktree if a
  contributor wants to dry-run locally.

## Tests

Per `.claude/instructions/testing-standards.md` "Tests exercise public
APIs only" — write tests against `parse_entry_file`,
`infer_next_version`, `validate_release_as`, and the `lint.py` CLI's
argv/exit-code surface. Do not reach into private parser state.

`scripts/changelog/tests/test_version_logic.py`:

- One test per row of the bump table (six rows × the shape of the
  table).
- The 0.x demote-to-minor rule for `break`.
- `infer_next_version` aggregating multiple entries (largest bump wins).
- `validate_release_as` happy path: single override > inferred, returns
  cleanly.
- `validate_release_as` failure: override `<=` inferred (boundary cases
  `==` and `<`).
- `validate_release_as` failure: two files with conflicting overrides.
- `validate_release_as` happy path: two files with the same override
  (idempotent agreement passes).
- Parser tests: required fields, type/nested-key mismatch, unknown
  type, unknown package, malformed YAML — each produces a
  `ChangelogValidationError` whose message names the file and field.

`scripts/changelog/tests/test_lint.py`:

- File-presence check — passes when at least one matching file is in
  the diff; fails otherwise; bypassed by `no changelog` label.
- Filename `pr-<N>-*.yml` regex with `<N>` matching the PR number.
- Schema lint over multiple files — first failure stops the run with
  a clear message.
- `release-as` lint integration — wires through to the version_logic
  validator with a current-tag fixture.

These tests need to run with the project's pytest collection. Two
options: (a) move them under an existing package's tests/ tree, or
(b) add `scripts/changelog/tests/` to `pyproject.toml` `pythonpath`

- `scripts/test.sh` UNIT_TEST_PATHS. Pick (b) — keeps the
  script self-contained alongside its source and matches the
  `scripts/verify_workspace_deps.py` pattern (its tests live under
  `tests/test_verify_workspace_deps.py` because there was no
  `scripts/tests/`; adding the convention here is the cleaner path).

If pytest collection from outside `packages/*/tests/` proves to need
larger plumbing changes (`scripts/check-package-coverage.sh` walks
`packages/*/pyproject.toml`), fall back to placing the tests under
an existing tests tree and document the indirection. Coverage on
the `scripts/changelog/` tree itself is out of scope for the
per-package floors — these are tooling scripts, not shipped service
code.

**Update during implementation:** keeping `scripts/changelog/tests/`
self-contained avoided touching `scripts/check-package-coverage.sh`
and the per-package pytest configs. The tests run via a dedicated
`task changelog:test` invocation from `scripts/changelog/test.sh`,
mirrored as a CI job in `.github/workflows/changelog-lint.yml`.
This keeps script-tooling tests off the workspace coverage gate
(no shipped-code measurement) while still gating them on every
PR. The typecheck gate (`task typecheck`) intentionally scopes
mypy/pyright to `packages/*/` and the workspace `tests/` tree —
matching the existing precedent for `scripts/verify_workspace_deps.py`.
Manually verified `scripts/changelog/version_logic.py` and
`scripts/changelog/lint.py` clean under `mypy --strict`; pyright
strict flags `Any`-leakage from `yaml.safe_load`'s untyped return,
which the existing workspace mypy override (`yaml` →
`ignore_missing_imports`) deliberately accepts. Bringing
`scripts/` under the typecheck gate is a sweeping change worth
its own PR (would also pull in `verify_workspace_deps.py` and
`design-generate.sh`'s python helpers).

## Required check registration

The new workflow's job name (`changelog-lint`) must be added to the
`main` branch ruleset's required-check list. This requires repo
admin and cannot land in this PR — flag it in the PR body for the
maintainer to flip post-merge.

## Standards review

- **Coding standards** — types annotated, dataclasses used for
  structured values, enum for the type field, validation function
  named with a verb.
- **Service design** — N/A (no service surface). PyYAML uses
  `safe_load`.
- **Release and hygiene** — REUSE.toml entry for `.gitkeep`; all new
  files carry SPDX headers.
- **Testing** — public-API-only tests; coverage of every bump table
  row plus the `release-as` boundary cases.
- **Tooling and CI** — workflow runs the lint; no new tools needed
  (uses `python3` and stdlib + the already-available `pyyaml` from
  the workspace venv via `uv run`). New `task changelog:test` task is
  workspace-specific and intentionally excluded from
  `verify-standards.sh` REQUIRED_TASKS.

## Acceptance checklist

- [ ] `changelog/@unreleased/.gitkeep` committed.
- [ ] `scripts/changelog/version_logic.py` with documented public
  API and unit tests for every bump table row + release-as
  invariant cases.
- [ ] `scripts/changelog/lint.py` CLI used by the workflow.
- [ ] `.github/workflows/changelog-lint.yml` enforcing the four checks.
- [ ] `CONTRIBUTING.md` section on the YAML schema.
- [ ] `changelog/@unreleased/pr-<N>-*.yml` for this PR (added once the
  PR number is known).
- [ ] Required-check registration documented in PR body.
- [ ] PR title uses the new Palantir prefix list (`feature(ci): ...`).
- [ ] DCO sign-off on every commit.
