<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0031 — Renovate custom managers + Dependency Submission API for CI tool bumps

## Status

Accepted — 2026-04-23.

## Context

`.github/actions/setup-toolchain/action.yml` consumes a set of release
binaries pinned by `version` + `sha256` in `.github/tool-versions.yaml`
(shellcheck, shfmt, ruff, taplo, keep-sorted, ripsecrets, treefmt,
go-task, d2). Dependabot's `github-actions` ecosystem only reads
`uses:` refs — it has no way to track version literals sitting inside
a custom YAML manifest, and no way to recompute the sibling sha256
when the upstream release changes.

As a result, before this ADR, every CI-tool bump required a manual sweep:
fetch upstream, bump the literal, recompute the hash, land a PR. Bumps
lagged and a CVE in any of those tools produced no signal against the
repo.

Related issues: #157 (install.sh sha256 pinning — lands alongside),
#87 (central tool-versions manifest — landed first so a single file
carries every literal).

## Considered alternatives

### Status quo — manual sweep

Land tool bumps by hand as the need arises (e.g. during a CVE triage,
or when a workflow breaks on an upstream API change).

**Rejected** because:

- Bumps lag real releases; at the time of writing all pinned tool
  versions were 3–12 months behind upstream.
- There is no CVE alert channel: GitHub's Dependabot Alerts surface
  depends on the Dependency Graph recognising the package, which
  means the version literal has to be visible to a supported
  ecosystem. `.github/tool-versions.yaml` is not.

### A home-grown scheduled workflow

A `cron:`-scheduled workflow that queries upstream GitHub release
APIs, computes sha256s, and opens PRs.

**Rejected** because:

- Reimplements ~half of Renovate (throttling, retry, rebase-on-conflict,
  grouping, on-call quiet hours).
- Still doesn't surface CVE alerts — that requires the Dependency
  Submission API path below regardless.

### SBOM-only signal (no bump channel)

Submit an SBOM for the pinned tools via the Dependency Submission API
so Dependabot Alerts fire, but leave version bumps fully manual.

**Rejected** because:

- Solves the CVE-alert half but not the bump-lag half.
- We already need a post-upgrade hook to recompute sha256s; Renovate
  provides that.

## Decision

Adopt **Renovate with custom managers** for automated bump PRs, and
complement it with the **GitHub Dependency Submission API** for CVE
signal.

### Renovate custom managers

- Config lives at `.github/renovate.json` — versioned in-repo so the
  behaviour is reviewable and auditable.
- One custom manager per tool, each targeting
  `.github/tool-versions.yaml` with a regex that captures the
  `version:` literal and points Renovate at the upstream datasource
  (`github-releases` for the GitHub-released tools, `pypi` for
  mdformat and friends).
- A repo-local post-upgrade task (`scripts/renovate/recompute-sha256.sh`)
  runs after each version bump and rewrites the sibling sha256 fields
  in the manifest so the version and hash never diverge in a
  Renovate-authored PR.
- d2 moves off `curl ... | sh` to a pinned release-asset binary
  (resolves #157 + #205 together) so it participates in the same
  Renovate channel as the other tools.
- Renovate and Dependabot share the repo: Dependabot continues to own
  `pip`, `github-actions`, and `npm`; Renovate owns the
  tool-versions manifest. There is no overlap.

### Dependency Submission API

- A scheduled workflow (`.github/workflows/dependency-submission.yml`)
  builds a snapshot of the tool-versions manifest and POSTs it to
  `/repos/{owner}/{repo}/dependency-graph/snapshots`.
- Snapshot uses PURLs (`pkg:github/koalaman/shellcheck@v0.10.0`,
  `pkg:pypi/mdformat@0.7.22`, …) so Dependabot Alerts fire on the
  same advisory ingestion path as any first-class ecosystem.
- Runs on each push to `main` and on a weekly cron so the snapshot
  stays current between pushes.

### Verification

`scripts/verify-standards.sh` asserts `.github/renovate.json` exists;
a dropped config would silently regress the whole policy.

## Consequences

**Positive:**

- Every tool in `.github/tool-versions.yaml` gets automated bump PRs
  with a recomputed sha256; no more version/hash drift.
- CVE alerts fire through the existing Dependabot Alerts surface.
- d2 is on the same integrity and auto-bump footing as every other
  binary tool.

**Negative / accepted trade-offs:**

- Renovate custom managers are regex-based. A breaking change to the
  manifest layout needs a corresponding update to the matcher, or
  bumps silently stop landing. Guarded by the verify-standards check
  (config presence) plus the convention of colocating matcher and
  manifest.
- The post-upgrade `recompute-sha256.sh` command must be added to
  Renovate's `allowedPostUpgradeCommands` allow-list on the Renovate
  installation's org/repo settings. Documented in
  `.claude/instructions/tooling-and-ci.md`.
- Installing the Renovate GitHub App is a one-time manual step not
  captured in-repo. The config ships ready; enabling it is a
  checkbox in the Renovate dashboard.
- The Dependency Submission workflow runs with
  `contents: write, id-token: none` and is gated on the push/schedule
  trigger — no pull-request path — so a malicious PR cannot poison
  the snapshot.

**Follow-up gaps (none blocking):**

- Future tool additions require both (a) a new manifest entry and
  (b) a new Renovate custom manager entry. Documented under
  `tooling-and-ci.md` § *Central tool-versions manifest*.
