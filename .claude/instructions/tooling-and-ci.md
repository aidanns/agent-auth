<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Tooling and CI

Standard tools to adopt and wire into CI and git hooks. When adding a new
tool, integrate it into `treefmt` (if it's a formatter) and `lefthook`
(if it should run on pre-commit).

## Language-specific

See language-specific instruction files for tooling tied to a particular
language: `python.md`, `bash.md`.

## YAML

- **YAML files use the `.yml` extension** — every committed YAML file
  in this repository ends in `.yml`. Tools that fix the filename
  (Taskfile, lefthook, GitHub Actions, Dependabot, changelog entries)
  already require `.yml`; project-owned configs (docker-compose,
  OpenAPI specs, the tool-versions manifest, design source-of-truth
  files) follow the same rule so contributors do not have to remember
  which extension a given file wants. `scripts/verify-standards.sh`
  fails the build if any committed `*.yaml` file appears in the tree.

  Runtime user-authored files referenced from in-tree code by string
  literal (`~/.config/<svc>/config.yaml`, `credentials.yaml`) are not
  project files and are out of scope for this rule.

## Markdown

- **`mdformat`** — formatting with plugins for tables and GitHub-flavoured
  Markdown.

## TOML

- **`taplo`** — linting and formatting for TOML config files.

## Security

- **`ripsecrets`** — pre-commit hook to prevent accidental secret commits.
  Preferred over alternatives for speed (Rust-based).
- **Dependabot** (or Renovate) — automated dependency updates for
  vulnerability fixes.

## Orchestration

- **`go-task`** — task runner with `Taskfile.yml` at the repo root. Every
  operation (build, lint, test, release) should be discoverable via
  `task --list`. Keep `scripts/*.sh` implementations; have the Taskfile
  dispatch to them. Project-specific tasks (running a local service
  CLI, a one-off domain command) are fine to add to `Taskfile.yml`, but
  must **not** be added to the `REQUIRED_TASKS` list in
  `scripts/verify-standards.sh`: that list is reserved for task names
  mandated by this cross-project tooling standard so the check stays
  portable to other repositories adopting it.
- **`treefmt`** — formatter/linter multiplexer. Run all formatters under one
  command with consistent behaviour.
- **`lefthook`** — git hook manager. Commit a `lefthook.yml` that runs
  `ripsecrets`, `treefmt`, and quick unit tests on pre-commit.
- **`keep-sorted`** — annotate sorted blocks (imports, dependency lists,
  allow-lists) so they stay sorted automatically.

## CI

### Workflow layout

The repository uses a uv-style nested `workflow_call` structure (issue
440). Each cadence has a single **parent orchestrator** that calls
**child workflows** via `uses: ./.github/workflows/<child>.yml`.
Children live alongside the orchestrators in `.github/workflows/`;
their `on:` block declares `workflow_call` only — the parent owns
the `pull_request` / `push` trigger surface for the cadence. The
exception is `pr-lint.yml`: it stayed top-level after the validator
migration in #463 because its two residual jobs
(`pr-title-types-self-test`, `predict-release-impact-self-test`) are
meta self-tests on workflow YAML / lint constants, not per-PR
checks. It triggers on `pull_request` directly; its file header
documents the retention rationale.

The three parent orchestrators today:

- **`ci.yml`** — every PR-time check. Top of the file is a `plan`
  job that emits gating booleans (label-driven outputs like
  `label_no_changelog` and `label_automerge`; changed-files outputs
  like `python_changed`, `bash_changed`, `docs_changed`; event-kind
  booleans like `event_is_pull_request`, `event_from_external_repo`).
  Every other job in `ci.yml` is a `workflow_call` child
  (`check-fmt`, `check-lint`, `check-security`, `check-changelog`,
  `check-publish`, `check-release`, `check-pull-request`,
  `check-standards`, `check-docs`, `test-unit`, `test-integration`,
  `test-smoke`, `test-system`, `build`).
- **`nightly.yml`** — daily-cadence checks (`mutation` today). Cron
  at 04:00 UTC.
- **`weekly.yml`** — weekly-cadence checks (`bench`,
  `open-ssf-scorecard`). Cron at 05:00 UTC Sunday (offset from
  `nightly.yml` so the runner queue is not doubled-up).

Bot workflows (`merge-bot.yml`, `changelog-bot.yml`,
`release-bot.yml`, `dependabot-adaptor-bot.yml`) are NOT
orchestrators — they have no children and consume PR / `push` /
`workflow_run` events directly. The `### Bot listener trigger surface` section below documents what each one listens to.

### Single repo-wide `required-checks-passed` aggregator

`ci.yml` ends with a `required-checks-passed` job whose `needs:`
lists every child. Branch protection on `main` references **only**
`ci / required-checks-passed`. Adding a new child is a one-line
edit to that `needs:` list — branch protection never has to be
touched. ADR 0046 documents this as the single repo-wide aggregator.
Per-workflow aggregators inside intermediate orchestrators
(`check-fmt.yml`, `check-lint.yml`, `check-security.yml`,
`check-pull-request.yml`, `nightly.yml`, `weekly.yml`) are NOT
allowed: GitHub already collapses a `workflow_call` child's overall
result into `needs.<child>.result` for the calling workflow, so an
intermediate aggregator only adds a redundant runner-startup tax.

The aggregator's logic is intentionally strict: per issue 441, any
`needs.*.result` other than `success` is treated as a failure —
including `skipped`. A child that legitimately opts out via `if:`
must surface a `success` outcome (e.g. via a short-circuit step)
rather than skipping the job, so the aggregator can rely on
`success` meaning "the check ran and passed" rather than "the check
ran or skipped".

The one carve-out is `ci.yml`'s verified-prior-success path for
`labeled` / `unlabeled` re-runs (issue 527). When the head SHA
already has a non-failing conclusion for every diff-dependent child,
those children skip via an `if:` gate and the aggregator relaxes the
`skipped = failure` rule for that specific set, gated on the
`diff_dependent_jobs_already_passed` flag emitted by `plan`. The
metadata-dependent children (`check-changelog`, `check-pull-request`)
keep the strict contract because their inputs (PR labels, PR
metadata) can change without the head SHA changing.

### Naming conventions

ADR 0046 collapses three orthographies onto one mechanical rule:
the artefact's `name:` is its own filename / directory. No per-
acronym judgement calls; no coordinated rename when a file moves.

- **Workflow filenames** — kebab-case, `.yml` extension. When ≥2
  workflows share a domain (`check-*`, `test-*`, `release-*`,
  `*-bot`), use a family prefix; bare single-word filenames are
  reserved for orchestrators (`ci.yml`, `nightly.yml`, `weekly.yml`)
  and standalone children whose name has no family. Suffix policy:
  `-bot` for workflows that author commits / labels back to the PR
  (`merge-bot.yml`, `changelog-bot.yml`, `release-bot.yml`);
  `-adaptor` for ones that wrap an external system to fit our
  conventions (`dependabot-adaptor-bot.yml`); no suffix otherwise.

- **Workflow `name:` field** — kebab-case, equal to the filename
  minus `.yml`. `merge-bot.yml` reads `name: merge-bot`; `ci.yml`
  reads `name: ci`. `scripts/verify-standards.sh` enforces this.

- **Composite-action `name:` field** — kebab-case, equal to the
  directory name under `.github/actions/`.
  `.github/actions/setup-toolchain/action.yml` reads
  `name: setup-toolchain`. `scripts/verify-standards.sh` enforces
  this.

- **Job IDs** — kebab-case, matching what shows up as the
  required-status-check display name when a job is wired into branch
  protection. **Matrix variants use the parens style**:
  `unit-tests (<package>)`, `integration-tests (<package>)`,
  `analyze (python)`, `install-from-wheels (<package>)`. The
  flat-suffix form (`integration-agent-auth`,
  `unit-agent-auth-common`) is non-conforming. The parens form
  preserves a stable parent name across variants so a CI dashboard
  can fold all variants under one row.

- **Job `name:` field** — drop it for non-matrix jobs. GitHub falls
  back to the job ID, which is already the kebab-case identifier
  branch protection sees. Matrix jobs keep a parens-template
  `name:` (e.g. `unit-tests (${{ matrix.package }})`) so each row
  publishes a stable, distinct check-run name.

- **Step `name:` fields** — Title Case prose, no trailing period;
  acronyms, tool names, and proper nouns retain their natural form
  ("Run treefmt --ci", "Install uv", "Build Release Artefacts").
  The existing tree mostly uses Sentence-case imperatives — those
  are not retroactively rewritten in the ADR 0046 cutover; the rule
  applies forward, and `verify-standards.sh` does not enforce step
  casing.

### Where a new check goes

Pick the orchestrator by cadence and trigger surface:

- **PR-time check** — child of `ci.yml`. Pick the right parent slot:

  - Formatting / lint drift → `check-fmt.yml`.
  - Type checks, lint rules, language-specific static analysis →
    `check-lint.yml`.
  - Secrets scans, SAST, dependency review / submission →
    `check-security.yml`.
  - Changelog presence / format → `check-changelog.yml`.
  - PR-metadata validators (DCO, title prefix, body shape) →
    `check-pull-request.yml`.
  - Project-standards canaries (`scripts/verify-standards.sh` and its
    siblings) → `check-standards.yml`.
  - Docs build → `check-docs.yml`.
  - Release dry-run / publish-readiness → `check-release.yml` /
    `check-publish.yml`.
  - Production-artefact build → `build.yml`.
  - Per-package unit / integration / smoke / system tests →
    `test-unit.yml` / `test-integration.yml` / `test-smoke.yml` /
    `test-system.yml`.

  If no existing parent is the right home, add a new direct child of
  `ci.yml` (filename `<verb>-<noun>.yml`; `name:` field equals the
  filename minus `.yml` per ADR 0046) and append its job ID to
  `ci.yml`'s `required-checks-passed.needs:` list.

- **Daily-cadence check** — child of `nightly.yml`. Append the new
  `<child>.yml` alongside `mutation`, add it to the aggregator's
  `needs:`.

- **Weekly-cadence check** — child of `weekly.yml`. Same shape as
  nightly; runner-queue scheduling lives in the cron at the top of
  the file, so no extra coordination needed.

- **Cross-cutting bot logic** that consumes other workflows'
  completions — standalone workflow with a `workflow_run:` listener.
  `merge-bot.yml` is the canonical example: its listener is scoped to
  `workflows: [ci]` (issue 467) so a green `ci` run is the single
  signal that every gate passed. Do not add a parallel listener for
  a child orchestrator; `ci.yml`'s `required-checks-passed` already
  reflects every child's outcome.

### Branch protection

A single ruleset entry on `main` requires
`ci / required-checks-passed`. Adding a new PR-time child requires
zero ruleset changes — the child is already covered transitively
through the aggregator.

### Bot listener trigger surface

- `merge-bot.yml` listens on `pull_request: types: [labeled]`
  (primary, for `automerge` label application),
  `workflow_run: workflows: [ci]` (sticky retry once `ci` completes),
  `pull_request_review`, `push: branches: [main]` (sweep open
  `automerge` PRs when `main` advances), and `workflow_dispatch`
  (maintainer break-glass / sweep fan-out). The `workflow_run`
  listener is intentionally scoped to the single parent orchestrator
  `ci`; the previous broader listener was collapsed in issue 467
  once the aggregator became the single required check.
- `changelog-bot.yml` listens on
  `pull_request: types: [opened, edited, synchronize, unlabeled]`
  directly (NOT `pull_request_target`) so a fork PR cannot mint a
  write-token from this workflow. It does not need to wait for
  `ci.yml` because its decisions depend only on PR metadata + the
  diff, both of which the `pull_request` event already carries.

### Cutover order when restructuring

When introducing a new parent orchestrator, splitting an existing
child, or moving jobs between children, the safe sequence is:

1. **Add new** — land the new parent / child / job alongside the
   existing one. Both run in parallel.
2. **Run in parallel** — leave both in place across at least one
   merge cycle so failure modes surface against real PRs, not just
   synthetic ones.
3. **Flip the ruleset** — only after the new aggregator (or new
   required check) has demonstrated green runs against PRs the old
   one also approved, switch branch protection to point at the new
   `<workflow> / <aggregator-job-id>` check.
4. **Delete the old** — remove the legacy workflow file and any
   references to its check names in the same PR that flips the
   ruleset (or in the immediate follow-up). Do not leave the legacy
   file in the tree as a "just in case".

### Tooling rules

- **Test runner script** — ensure a single-command test runner exists (e.g.
  `scripts/test.sh`) so the full test suite runs with one command.

- **Wire all check scripts into CI** — every repeatable check script must
  have a CI workflow.

- **Central tool-versions manifest** — pinned CLI tool versions live in a
  single YAML file at `.github/tool-versions.yml`. Both the CI composite
  action (`.github/actions/setup-toolchain/action.yml`) and the local
  preflight (`scripts/verify-dependencies.sh`) read this file; neither
  consumer may hard-code a version literal that also lives in the
  manifest. `scripts/verify-standards.sh` enforces that canary.

  CI installs the exact manifest version for reproducibility.
  `verify-dependencies.sh` enforces the pin as a **minimum within the
  same major** — local dev environments (brew, apt, asdf) frequently
  ship ahead of CI, so `>= manifest_version` passes, an older version
  or a different major fails. Renovate custom managers target the
  manifest so a single bump propagates to both environments.

  **Adding a tool to the manifest:** add an entry with `version:` and
  (for release-binary installs) `sha256_linux_x86_64:`; wire the
  install into `.github/actions/setup-toolchain/action.yml`; add a
  matching `customManagers` block to `.github/renovate.json` with the
  right `datasource` + `depName` for upstream releases; teach
  `scripts/renovate/recompute-sha256.sh` the asset URL template; and
  add the PURL template to
  `scripts/ci/submit-dependency-snapshot.sh` so CVE alerts cover the
  new tool. `scripts/verify-standards.sh` asserts the manifest and
  Renovate config stay aligned.

- **Renovate custom managers + Dependency Submission API** — Renovate
  (installed as a GitHub App, configured via `.github/renovate.json`)
  owns the automated bump channel for the tool-versions manifest;
  Dependabot continues to own `pip`, `github-actions`, and `npm` (no
  overlap). Each tool has a regex custom manager that captures its
  `version:` literal and points at the upstream datasource; a
  post-upgrade task runs `scripts/renovate/recompute-sha256.sh` so the
  sibling sha256 is recomputed in the same PR. The
  `recompute-sha256.sh` command must be added to
  `allowedPostUpgradeCommands` in the Renovate installation's repo or
  org settings.

  In parallel, `.github/workflows/dependency-submission.yml` builds a
  PURL snapshot from the manifest on push-to-main and weekly, then
  POSTs it to the Dependency Graph. Dependabot Alerts ingest the
  snapshot so CVEs for any listed tool fire on the standard alerts
  surface. See ADR 0031.

- **Pin sha256 for tool binary downloads** — any CI step that downloads a
  CLI binary directly (curl/wget from a release CDN) must verify the
  artefact against a sha256 pinned in the repository before extracting or
  installing it. Pair the version input with a sibling `<tool>-sha256`
  input so version bumps and hash updates travel together. Verify with
  `echo "<sha256>  <path>" | sha256sum -c -` immediately after download
  and before any `tar`/`install`/`gunzip` step. A failed check must abort
  the action — never fall back to the unverified binary. Pinning in-repo
  is preferred over fetching an upstream `checksums.txt`, because the
  checksum file would travel over the same TLS channel as the artefact
  it claims to verify.

  The same rule applies to **install scripts fetched over the network**
  (`curl ... | sh`, `curl ... | bash`). Replace the pipe with
  download → `sha256sum -c` → execute, with the hash pinned in the
  tool-versions manifest and bumped together with any upstream change.
  A ref-pin alone (e.g. a commit SHA in the URL) is not sufficient: the
  install.sh body at that ref is still editable if the upstream repo is
  a moving target, and the pipe form never sees the bytes it ran.
  `verify-standards.sh` asserts the absence of unverified pipes in
  `setup-toolchain/action.yml`.

- **Pin release-affecting GitHub Actions to commit SHAs** — third-party
  `uses:` references in any workflow that holds `id-token: write`,
  `contents: write`, or otherwise sits on the release path must be pinned
  to a full 40-character commit SHA, not a floating `@vX` tag. A
  compromised action release on a floating tag can otherwise siphon the
  runner's OIDC token or substitute a malicious signing binary in-flight.
  Use the format `uses: ORG/REPO@<sha> # vX.Y.Z` — Dependabot reads the
  trailing comment to track upgrades and rewrites both the SHA and the
  comment on each bump, keeping the pin reviewable.

  Scope today: `.github/workflows/release-bot.yml`, the SLSA provenance
  generator referenced from `release-bot.yml`, and
  `.github/actions/setup-toolchain/action.yml` (indirectly part of the
  release path). Read-only PR-time workflows under `ci.yml` stay on
  floating-major tags — their blast radius is small enough that the
  review cost of SHA-pinned bumps outweighs the benefit. Local composite
  actions referenced as `uses: ./...` are version-locked to the repo
  commit itself and need no extra pinning.

  Explicit exception: `slsa-framework/slsa-github-generator`'s reusable
  workflows **must** be referenced by semantic-version tag
  (`@v2.1.0`), not by commit SHA. The SLSA generator introspects its
  own `@ref` to certify the builder identity in the emitted
  provenance; a SHA ref produces an invalid (or unverifiable)
  attestation. See
  https://github.com/slsa-framework/slsa-github-generator/blob/main/internal/builders/generic/README.md#referencing-the-slsa-generator.
  Leave a comment at the call-site explaining the exception so the
  next maintainer doesn't "harden" it by mistake.

## IDE

- **VS Code project** — generate or commit a `.vscode/` directory covering
  recommended extensions, debug configurations, and workspace settings.
