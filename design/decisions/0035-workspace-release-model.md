<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0035 — Keep a single workspace-wide release train for now

## Status

Proposed — 2026-04-24.

Builds on [ADR 0026](0026-semantic-release-autorelease.md) (semantic-release
as autorelease driver) and [ADR 0032](0032-monorepo-workspace-split.md)
(uv workspace split). ADR 0032 explicitly deferred this question to a
follow-up; [#275](https://github.com/aidanns/agent-auth/issues/275) is
that follow-up.

## Context

[ADR 0032](0032-monorepo-workspace-split.md) split the repo into a uv
workspace of per-service subprojects under `packages/` and left the
release plumbing unchanged: one repo-wide `v<X>.<Y>.<Z>` tag, one
`CHANGELOG.md`, one semantic-release run on every push to `main`. The
post-split setup still bumps every package in lockstep — a `feat` in
`agent-auth` produces a new version for `things-cli` and
`agent-auth-common` even when neither changed.

`agent-auth-common` is the sharpest case for independent versioning.
It is a pure library with no console-script and zero non-stdlib
runtime dependencies; its consumers (the other workspace packages
today, external consumers in theory) benefit from a version number
that moves only when its own API moves. Every service package is a
less extreme version of the same argument.

The question is whether to pay the tooling cost now — one-time setup
of per-package semantic-release configuration, namespaced tags,
per-package changelogs, and CI publish jobs — against benefits that
currently have no consumer. Nothing in the workspace is published to
PyPI; `curl | bash` installers resolve straight from a Git
ref (`packages/<svc>/install.sh`), so the tag consumers are
humans reading release notes and CI jobs producing signed artefacts,
not version-pinning package managers.

The ground-truth inputs to this decision:

- Solo maintainer, pre-1.0. No external release cadence pressure.
- No external consumer of `agent-auth-common` as a library. The
  per-package `[tool.uv.sources]` pointer makes it a workspace
  dependency for the other packages; the PyPI distribution is
  reserved but not published.
- Every workspace package is already wired for per-package
  versioning: `[project] dynamic = ["version"]` +
  `[tool.setuptools_scm]` with `fallback_version` in each
  `packages/<svc>/pyproject.toml`. Switching each package to a
  namespaced tag pattern (`<svc>/v<X>.<Y>.<Z>`) is a config change
  per file, not a refactor.
- Commit scopes today are a mix: many commits carry a package scope
  (`feat(things-bridge):`, `refactor(agent-auth):`), but repo-wide
  commits (`refactor:`, `ci:`, `build:`) and cross-package commits
  (`refactor(things-bridge,things-cli):`) are normal and useful.
  Per-package semantic-release filters commits by scope, so a
  full migration would force every commit to carry at least one
  package scope to decide which train it rides.

## Considered alternatives

### Per-package semver across every workspace package

Run semantic-release once per package, each with its own
`.releaserc.mjs`, tag prefix (`agent-auth/v<X>.<Y>.<Z>`,
`things-cli/v<X>.<Y>.<Z>`, …), and `CHANGELOG.md`. Commit scopes
filter which trains are cut. `semantic-release-monorepo` (community
plugin) is the standard way to wire this; a plain matrix of
`semantic-release` runs with per-package config is the alternative
and avoids adding a community dependency to the release path.

**Rejected for now** because:

- The benefits it unlocks — per-package consumer pinning, per-package
  changelogs, independent 1.0 readiness — have no consumer today.
  Nothing is on PyPI; no downstream project pins
  `agent-auth-common`; no service is close to an independent 1.0
  decision. The tooling cost is paid now for a benefit deferred to
  an unknown future.
- Scope hygiene becomes load-bearing where today it is advisory.
  A repo-wide refactor commit (`refactor: rename FooError → BarError`)
  would either trigger releases on every package (by being matched
  by every train) or no package (by being filtered out by every
  train) depending on how the filter is written. Either resolution
  forces a change in how we write commits that is unrelated to the
  release-semantic value of the decision.
- The SLSA (ADR 0020) + cosign + SBOM (ADR 0016) path was designed
  around one workflow producing one artefact set per release. A
  per-package split multiplies that workflow by the number of
  packages (seven today: `agent-auth`, `agent-auth-common`,
  `things-bridge`, `things-cli`, `things-client-cli-applescript`,
  `gpg-bridge`, `gpg-cli`). The per-package
  publish jobs are workable — the existing `release-publish.yml`
  fires on `push: tags: v*` and can be generalised — but each adds
  a signing identity, an attestation file, and a matrix leg to every
  release, which is expensive surface to carry without a concrete
  consumer asking for it.
- Changelog quality regresses further. `CHANGELOG.md` today
  aggregates every commit under one version heading — coarse but
  complete. Splitting into seven changelogs creates the opposite
  problem: a cross-package refactor has to be attributed to one
  package's changelog, misleadingly, or duplicated across all of
  them, noisily.

### Hybrid: split `agent-auth-common` only, keep services on the single train

Treat `agent-auth-common` as a stand-alone library with its own
`agent-auth-common/v<X>.<Y>.<Z>` tag stream, `packages/agent-auth-common/CHANGELOG.md`,
and semantic-release run driven by commits scoped to
`agent-auth-common`. The service packages continue on the current
repo-wide `v<X>.<Y>.<Z>` tag.

**Rejected for now** because:

- Pays most of the cost of the full per-package split (a second
  semantic-release config, a second tag namespace, a second
  publish job, a second changelog, scope-filter rules in both
  trains so commits don't trigger both) to solve for the one
  package with the least immediate consumer pressure — nothing
  external consumes `agent-auth-common`.
- Introduces a two-class system in the workspace: one package has
  its own release cadence, the rest share one. Operators reading
  `CHANGELOG.md` for a service would need to know that a
  dependency on `agent-auth-common` means also reading a second
  changelog, with no indicator in the aggregate `CHANGELOG.md`
  that the common package moved independently that week.
- If the full split becomes the right answer later, doing it in
  one step is simpler than first moving common and then the rest.
  A migration that splits common first and the services later
  mostly adds a state where the services' lockstep behaviour is
  underscored by explicit contrast.

### Separate Git repositories, one per package

Move each package into its own Git repo with its own tag namespace,
as [ADR 0032](0032-monorepo-workspace-split.md) briefly considered.

**Rejected** on the same grounds ADR 0032 used to keep the
workspace together: the cross-service integration tests live
somewhere that has to reach every package, and splitting repos
forces either a release-tag dependency from integration tests onto
every service or a separate integration-tests repo with its own
release coordination problem. The workspace is the reason a future
split (whether of tags or of repos) can be executed; forcing it
now undoes the structural decision that made this ADR possible.

## Decision

Keep the single workspace-wide `v<X>.<Y>.<Z>` train produced by
semantic-release. Make no changes to `.releaserc.mjs`,
`CHANGELOG.md`, `scripts/release.sh`, or
`scripts/verify-standards.sh`.

Carry forward from ADR 0032 that every workspace package keeps its
own `[project] dynamic = ["version"]` + `[tool.setuptools_scm]`
block. This means that on the day this ADR is revisited and the
decision flips, per-package version resolution works without a
source-code change — only the tag namespace (and the surrounding
CI plumbing) has to move.

### Revisit triggers

Revisit this ADR when **any** of the following becomes true. When
the trigger fires, open a new ADR that either flips this decision
or records why the trigger doesn't warrant a change; do not amend
this one.

1. **External consumer pinning.** A project outside this repo starts
   pinning a version of `agent-auth-common` (or any other workspace
   package) from PyPI or a Git tag. At that point the cosmetic
   lockstep bump becomes a real churn cost for the consumer.
2. **First independent 1.0.** Any workspace package reaches a state
   where its maintainer wants to commit to SemVer 2.0.0 stability
   guarantees (cf. ADR 0026's graduation-to-1.0 note) ahead of the
   other packages. Independent 1.0 readiness is incompatible with
   a shared tag stream — the other packages would be forced to
   graduate in lockstep even if their APIs are not stable.
3. **Divergent release cadence.** One package's release pressure
   (fix frequency, user-visible change rate) materially diverges
   from the rest so that the aggregate changelog stops being
   readable. The operational signal is a reviewer complaining that
   they can't tell which package a release affects without reading
   the commits.

### Documented posture

Record this decision in the project posture so contributors and
future readers of `.releaserc.mjs` understand the lockstep is
intentional, not an oversight:

- Leave the existing ADR 0032 follow-up note ("Per-package release
  automation … Tracked separately once the workspace has settled")
  in place; this ADR is that tracking record.
- No CLAUDE.md change. The release-model decision lives in the
  ADR; the commit-message convention (`feat:` / `fix:` with
  optional package scope) is unchanged and already documented.

## Consequences

**Positive**

- Zero release-plumbing work right now. The existing
  semantic-release config, SLSA + cosign + SBOM pipeline, and
  break-glass `scripts/release.sh` all keep working unchanged.
- One `CHANGELOG.md` continues to capture every merged commit; a
  reviewer looking for "what changed in v0.10.0" reads one file.
- Commit-scope discipline stays advisory. Repo-wide refactors keep
  their natural unscoped `refactor:` / `ci:` / `build:` subjects
  without having to invent package scopes to satisfy a release
  filter.
- The per-package `setuptools_scm` blocks already in place mean the
  eventual flip is a configuration change, not a refactor. Code in
  each `packages/<svc>/pyproject.toml` is already forward-compatible
  with a per-package tag namespace.
- Consumer install story is unaffected. `curl | bash` installs still
  pull from `packages/<svc>/install.sh` at a Git ref; the repo-wide
  tag is the default reference point for "latest release of
  everything."

**Negative / trade-offs**

- `agent-auth-common` gets its version bumped every time any
  service releases. Cosmetic while nothing external pins it;
  a real churn cost the moment trigger 1 fires. Accepted
  explicitly.
- `CHANGELOG.md` entries aggregate across packages, so a reader
  interested in `things-cli` alone reads every release even when
  `things-cli` didn't change. Partial mitigation: every commit
  subject includes a `(<scope>)` when a single package is
  affected, so `grep '(things-cli)' CHANGELOG.md` is a workable
  per-package view. Not as clean as a per-package file; acceptable
  while the project has one reader.
- Independent 1.0 graduation is off the table until the decision
  flips. A package cannot ship a stability guarantee ahead of the
  others because it shares their tag stream. Accepted because no
  package is currently asking to graduate; the revisit trigger
  catches this directly.
- Release-tag provenance granularity is repo-wide. A signed artefact
  for `v0.10.0` asserts "this release of the repo" rather than
  "this release of `things-cli`." ADR 0020's SLSA attestations are
  per-artefact (per wheel), so the provenance gap is the release
  bundle's composition, not any one artefact's trustworthiness.
  Accepted on the same grounds as the changelog aggregation above.

**Neutral**

- Break-glass `scripts/release.sh` continues to work without
  modification. Its version-derivation logic parses `v<X>.<Y>.<Z>`
  from the latest tag and assumes a single tag namespace; that
  assumption stays valid.
- `scripts/verify-standards.sh` continues to enforce a single
  `CHANGELOG.md` at the repo root. No new verify-standards
  logic is introduced; the eventual flip adds regression checks
  for per-package changelogs at that point.

## Follow-ups

- GitHub issue: **implement per-package release model** if/when any
  revisit trigger fires. The issue should cover namespaced tag
  patterns (`<svc>/v<X>.<Y>.<Z>`), per-package `.releaserc` config,
  per-package `CHANGELOG.md`, scope-based commit filtering, and
  CI publish-job fan-out. Captured under #275 for now; open a fresh
  issue when the trigger fires so this ADR's follow-up doesn't
  accumulate decisions made under different contexts.
- PyPI publishing readiness — still deferred as in ADR 0032. A
  first PyPI publish of `agent-auth-common` would itself be a
  revisit trigger (it is the canonical "external consumer" event).
