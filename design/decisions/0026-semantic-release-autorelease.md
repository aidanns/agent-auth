<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# ADR 0026 — Migrate autorelease driver from Release Please to semantic-release

## Status

Accepted — 2026-04-22.

Supersedes the autorelease-driver choice in
[ADR 0016](0016-release-supply-chain.md). The remaining ADR 0016
decisions (keyless cosign, SPDX SBOM via Syft, REUSE 3.3, break-glass
`scripts/release.sh`, setuptools-scm as runtime version source) carry
over unchanged.

## Context

[ADR 0016](0016-release-supply-chain.md) established Release Please
(`googleapis/release-please-action@v4`, `release-type: simple`) as
the autorelease driver. Its "Considered alternatives" section
explicitly rejected semantic-release for two reasons:

1. Release Please batches changes into a reviewable release PR;
   the PR was the named pre-1.0 guardrail.
2. Semantic-release's plugin ecosystem was judged heavier than
   needed for CHANGELOG + tag management.

This ADR reverses that choice on maintainer preference for an
on-merge release model without a per-batch review PR, after weighing
the guardrail argument against the friction of an always-open
release PR on a solo-maintainer project. The PR commit-review step
absorbs the guardrail role.

No operational failure of Release Please drove the reversal — the
existing workflow has been running successfully since #106 landed.
This is a workflow-ergonomics decision, not a defect response.

## Considered alternatives

### Keep Release Please (status quo)

**Rejected** because:

- The release-PR model requires a second reviewer action (merge the
  release PR) for every release cut, which on a solo-maintainer
  project is pure overhead — the review content is derivable from
  the commits that opened the PR.
- The open release PR accumulates commits across multiple merges
  into a single release, delaying tag creation (and thus SLSA
  provenance, signed SBOMs, and downstream consumer visibility)
  behind the next manual merge.

### semantic-release with `dryRun` / manual approval gate

**Rejected** because:

- Adding a `workflow_dispatch` gate around semantic-release
  reconstructs the Release Please PR model without its
  batching benefit, giving us the worst of both.
- If a pre-1.0 guardrail is required beyond commit-review, the
  simpler response is to hold commits at the PR stage rather than
  gate their release.

### Migrate to `release-please-action` v5 (YAML config) only

**Rejected** because:

- Preserves the release-PR model we're rejecting; resolves a
  configuration-format question irrelevant to the motivating
  change.

## Decision

Replace Release Please with semantic-release as the autorelease
driver on every push to `main`.

- **Workflow**: `.github/workflows/semantic-release.yml` runs on
  `push: main` and `workflow_dispatch`. On a qualifying
  Conventional Commit since the last `vX.Y.Z` tag, it computes the
  next version, writes to `CHANGELOG.md`, creates a signed
  `vX.Y.Z` tag, pushes a `chore(release): ${version}` commit back
  to `main`, and creates a GitHub release. Non-qualifying pushes
  exit cleanly.
- **Configuration**: `.releaserc.json` with the standard plugin
  chain — `commit-analyzer`, `release-notes-generator`,
  `changelog`, `github`, `git` — driven by the
  `conventionalcommits` preset.
- **Pre-1.0 behaviour**: `commit-analyzer.releaseRules` demotes
  `BREAKING CHANGE:` from major to minor while in the 0.x range.
  Graduating to 1.0.0 means removing that rule from
  `.releaserc.json` and manually cutting the 1.0.0 tag (either
  via `task release -- 1.0.0` or by letting the next breaking
  commit trigger semantic-release once the rule is gone).
- **Versioning**: `setuptools-scm` remains the runtime version
  source. Semantic-release writes the tag only; it does not patch
  `pyproject.toml`. `uv build` derives the wheel version from the
  tag at build time in the existing tag-triggered
  `release-publish.yml`. No change to `release-publish.yml` is
  required — it still fires on `push: tags: v*`.
- **Credentials**: semantic-release authenticates via the same
  GitHub App provisioned for Release Please in #128
  (`RELEASE_PLEASE_APP_ID` + `RELEASE_PLEASE_APP_PRIVATE_KEY`).
  The token is minted per run via
  `actions/create-github-app-token` and consumed by semantic-release
  through `GITHUB_TOKEN`. Required permissions shrink slightly
  (`pull-requests: write` becomes reserved rather than load-bearing
  for the release flow), but no secret rotation is needed — see
  Follow-ups.
- **Guardrail**: pre-1.0 discipline moves to the PR commit-review
  step. Breaking changes demote automatically; accidental
  `feat:`-over-`fix:` escalations are caught by reading commit
  subjects at PR merge time.
- **Break-glass**: `task release` / `scripts/release.sh` are
  preserved untouched as the local fallback path.
- **Node runtime in CI**: semantic-release is a Node tool. The
  migration introduces `package.json` + `package-lock.json` at the
  repo root and `actions/setup-node` into `semantic-release.yml`.
  Dependencies are pinned by SHA in the lockfile; Dependabot's
  existing `npm` ecosystem entry (added below under Consequences)
  surfaces updates.

## Consequences

**Positive**

- Releases land the moment a qualifying merge reaches `main`,
  shrinking the gap between a fix being committed and consumers
  seeing it signed + attested.
- No always-open release PR to babysit or merge-conflict-resolve
  against every subsequent landing on `main`.
- Conventional-commit discipline becomes load-bearing rather than
  advisory — a mislabelled commit produces the wrong release, so
  review catches it at PR-merge time instead of at release-PR
  time.
- `CHANGELOG.md` and the GitHub release body derive from the same
  Conventional Commit source, eliminating drift between the two
  surfaces.

**Negative / trade-offs**

- The pre-1.0 guardrail weakens: there is no reviewable release PR
  between commit and tag. Mitigated by the PR-merge review step
  and the `releaseRules` BREAKING demotion; accepted as the
  intended effect of removing the PR gate.
- `CHANGELOG.md` content quality regresses from hand-authored
  Keep-a-Changelog prose (pre-migration) to commit-derived bullets.
  Mitigated by `CONTRIBUTING.md` guidance pointing contributors at
  rich commit bodies. Older [0.1.0] and [Unreleased] sections
  remain in the file in their original format; the generator
  prepends above them.
- First run will produce a CHANGELOG section describing commits
  already enumerated in the pre-migration `[Unreleased]` section —
  both will coexist until a maintainer prunes the duplicate.
  Accepted as a one-time artefact; the alternative (hand-cutting a
  `0.2.0` release immediately before the migration) adds scope
  without improving downstream visibility.
- Node toolchain in CI. `package.json` pins
  `semantic-release@24.2.1` and plugin versions; `package-lock.json`
  locks the transitive graph. Two advisories in `npm`'s own
  bundled deps (`brace-expansion` GHSA-f886-m6hf-6m8v moderate,
  `picomatch` GHSA-3v7f-55p6-f55p high) surface under `npm audit`
  and are not fixable via `npm audit fix` at our level. Neither
  affects our release path (we do not parse user-controlled globs
  in CI). Tracked as follow-up; accepted for now.
- A new Dependabot ecosystem (`npm`) must be added to
  `.github/dependabot.yml` so semantic-release pins stay current.
  Tracked as follow-up below.

**Neutral**

- The GitHub App and its secret names (`RELEASE_PLEASE_*`) are
  retained for migration continuity. Rename-to-`RELEASE_APP_*` is
  a future hygiene item; the prefix is a migration-era artefact,
  not a behaviour concern.
- `CHANGELOG.md`'s existing historical entries referencing "Release
  Please" are preserved. Rewriting history would violate Keep-a-
  Changelog stability guarantees; the text accurately describes
  the tooling at the time of each release.

## Follow-ups

- Rename `RELEASE_PLEASE_APP_ID` → `RELEASE_APP_ID` and
  `RELEASE_PLEASE_APP_PRIVATE_KEY` → `RELEASE_APP_PRIVATE_KEY` in
  repo settings and the workflow. Non-urgent; purely cosmetic.
- Add an `npm` ecosystem block to `.github/dependabot.yml` so
  Dependabot surfaces semantic-release + plugin updates.
- Re-evaluate the `npm audit` advisories (`brace-expansion`,
  `picomatch`) on the next `semantic-release` major — if they
  resolve, drop this note; if they persist, open an accept-risk
  follow-up.
- On the first post-migration release, prune the legacy
  `## [Unreleased]` section once its content has been captured by
  the auto-generated section.
- Graduating to 1.0.0: remove
  `{"breaking": true, "release": "minor"}` from
  `.releaserc.json` and run
  `task release -- 1.0.0` once to anchor the new major baseline.

<!-- REUSE-IgnoreEnd -->
