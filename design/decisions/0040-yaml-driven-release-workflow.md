<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0040 — YAML-driven release workflow with a maintainer-merged release PR

## Status

Accepted — 2026-04-25.

Supersedes the autorelease-driver choice in
[ADR 0026](0026-semantic-release-autorelease.md). The remaining ADR 0026
decisions (release-impact mapping that demotes BREAKING to a minor
bump while in 0.x) carry over and are now expressed in
`scripts/changelog/version_logic.py`'s bump table. Carries over from
[ADR 0016](0016-release-supply-chain.md) the supply-chain trust
chain (keyless cosign, SPDX SBOMs via Syft, setuptools-scm runtime
version, `release-publish.yml` artefact build), and from
[ADR 0020](0020-slsa-build-provenance.md) the SLSA-L3 provenance
chain. Builds on [ADR 0035](0035-workspace-release-model.md)
(single-train workspace release model — preserved here; the YAML
schema's `packages:` field is parsed but not yet acted upon).

## Context

Three months of operating semantic-release (per ADR 0026) surfaced
two pain points:

1. **Release content is derived from commit subjects.** A
   `==COMMIT_MSG==` block (introduced in [ADR 0037](0037-palantir-commit-prefixes-and-commit-msg-block.md))
   captures the squash-merge body but the rendered CHANGELOG only
   sees the *subject*. Anything user-visible that can't fit in 72
   characters lives in commit bodies the changelog ignores.
2. **No human gate before a tag is cut.** semantic-release runs on
   every push to `main` and pushes the tag immediately. The PR review
   gate is the only check; once a PR merges, the release ships before
   anyone has a second look. Pre-1.0 we accept that risk, but the
   model has no headroom for "pause this release while we double-
   check the upgrade notes" without disabling the workflow entirely.

#289 plotted the migration to a file-per-change YAML schema under
`changelog/@unreleased/` (#295 — landed as PR #303), with the release
itself driven by the YAML rather than commit subjects (#296 — this
ADR). The Palantir conventions also drove the new PR-title prefix set
(ADR 0037 + #290) which fed into the bump table here.

## Considered alternatives

### Keep semantic-release; render CHANGELOG from commit bodies

**Rejected** because:

- Commit bodies are not authored against a schema — every PR would
  need a parallel "release-notes paragraph" convention enforced by
  yet another lint, and the convention would still rely on prose
  parsing rather than structured fields.
- The "no human gate" pain point would be unchanged.

### Release Please (return to ADR 0016's predecessor)

**Rejected** because:

- Release Please derives the changelog from commit subjects (same
  data source as semantic-release) so it inherits issue 1.
- Switching back would re-introduce the per-batch release PR but
  with the same source-of-truth weakness.

### Build a custom Python-only release tool

**Rejected as out of scope here** but partially adopted: the
version-inference + YAML-parsing logic *is* a custom Python module
(`scripts/changelog/version_logic.py` from #295), reused unchanged by
the workflow described here. The workflow file itself stays as plain
GitHub-Actions YAML; building a generic CLI would couple work into
this PR that doesn't earn its keep yet.

## Decision

Replace semantic-release with two GitHub-Actions workflows backed by
the YAML schema from #295:

- **`release-pr.yml`** — runs on every push to `main`. Reads
  `changelog/@unreleased/pr-*.yml`, computes the next version via
  `version_logic.infer_next_version` + `apply_release_as`, renders
  `CHANGELOG.md` and the release-PR body, and opens / updates a PR
  on `release/<X.Y.Z>` titled `chore(release): <X.Y.Z>`.
- **`release-tag.yml`** — runs when a `release/X.Y.Z` PR merges.
  Tags `v<X.Y.Z>` on the merge commit (using a GitHub App token so
  the tag-push fires `release-publish.yml`), then creates a GitHub
  Release with the body re-rendered from the *moved* YAMLs under
  `changelog/<X.Y.Z>/`.

The existing `release-publish.yml` (artefact build, SBOM, cosign
signing, SLSA-L3 provenance) is kept *unchanged* — it still runs on
`push: tags: ['v*']`. Renaming it would invalidate SECURITY.md's
`--certificate-identity` recipe for any future release. The new
workflow that handles tag + GitHub-Release creation lives in
`release-tag.yml` instead.

### Sub-decisions

- **Branch naming: `release/<X.Y.Z>`.** Lets the publish workflow
  filter by head ref alone; the title check is the secondary defence.
- **Release-PR title: `chore(release): <X.Y.Z>`.** Matches the
  historic Conventional-Commits convention so existing tooling
  (verify-standards' required `task release` task; the CHANGELOG
  style) keeps reading without surprise.
- **Single source of truth for the bump table.** The workflow calls
  `version_logic.infer_next_version`. There is no second
  implementation in shell or workflow YAML to drift.
- **`==COMMIT_MSG==` block in the release PR.** The PR body is
  auto-rendered to satisfy `pr-lint.yml`'s commit-msg-block
  validator: prose-only paragraphs (no markdown bullets, no
  headings), wrapped at 72 chars, single `Signed-off-by:` trailer.
  The release notes (the human-friendly view) live below the block
  in the `## Review notes` section, alongside the file-move list and
  the rendered CHANGELOG section preview.
- **Bypass for `changelog-lint.yml` on `release/*` branches.** A
  release PR DELETES every `@unreleased/*.yml` (renaming them under
  `<X.Y.Z>/`) rather than adding one, so the file-presence check
  would fail closed. The release-pr workflow runs the same parser
  before opening the PR, so the schema check on the release branch
  is redundant. Bypass added at the workflow level (not inside
  `lint.py`) so the bypass surface stays visible.
- **Tag-pusher identity.** The release App
  (`semantic-release-agent-auth`, retained name pending a follow-up
  rename) mints a short-lived installation token that `release-tag.yml`
  uses to push the tag. Using the App rather than `GITHUB_TOKEN` is
  required so the tag push fires `release-publish.yml` — this
  constraint was first documented in ADR 0026 and applies unchanged.
- **PR-opener identity.** First cut uses the default `GITHUB_TOKEN`
  for `gh pr create / edit`. If the `main` ruleset later blocks PRs
  opened or merged by the workflow token, swap to the App. Tracked
  as a follow-up rather than a blocker since the failure mode is a
  visible CI error.

## Consequences

### Positive

- **Single source of truth for release notes.** The YAML files are
  the canonical record; the CHANGELOG, the GitHub Release, and the
  release PR are all renderings of the same data. Edits to release
  notes go through the YAML, not three parallel surfaces.
- **Maintainer review gate.** A release ships only after the
  release PR merges. Trivial today (auto-merge possible); load-
  bearing later when the project graduates to 1.0 and downstream
  consumers care about each release.
- **Simpler dependency footprint.** The repo loses
  `package.json`, `package-lock.json`, `.releaserc.mjs`, the
  `@semantic-release/*` toolchain, and the npm Dependabot ecosystem.
  CI no longer installs Node for the release path.
- **Closes #215.** Signed release commits are obviated — the bot no
  longer pushes a `chore(release):` commit. The release commit on
  the release branch is the maintainer's reviewed merge commit,
  which lands through the standard signed-commit ruleset.

### Negative / accepted trade-offs

- **Two-step release.** Cutting a release now requires a maintainer
  to merge the release PR. On a solo project this is overhead the
  previous flow avoided. Mitigated by `task release` (manual
  workflow dispatch) and by GitHub auto-merge if the maintainer
  trusts the auto-rendered notes.
- **Workflow complexity.** Two new workflow files + a Python module
  vs. semantic-release's single workflow. The Python module is
  unit-tested (mirroring `version_logic.py`); the workflow YAML
  branching is thin enough to exercise via the first real run on
  `main`.
- **Old releases keep their semantic-release commit author.** The
  historic `chore(release):` commits authored by
  `semantic-release-agent-auth[bot]` remain in `git log`. No attempt
  is made to rewrite history.

### Constraints imposed on future work

- **Per-package release trains (#275).** The YAML's `packages:`
  field is parsed by `version_logic.parse_entry_file` but ignored at
  version-inference time here. When #275 lands, the workflow needs
  to (a) compute one bump per package, (b) tag `<svc>-vX.Y.Z`
  alongside the workspace tag, and (c) carve the CHANGELOG by
  package. Today's single-train shape stays compatible by inferring
  one workspace-root version regardless of `packages:`.
- **CHANGELOG.md format.** The renderer emits the
  `## [X.Y.Z] - YYYY-MM-DD` heading + `### <Group>` subsections.
  Old sections (semantic-release-rendered) keep their bracket-link
  comparison heading and the project lives with the visual mismatch
  rather than rewriting historic sections.
- **The release App identity.** `semantic-release-agent-auth` is no
  longer accurate; renaming the App (and the
  `SEMANTIC_RELEASE_APP_*` repo secrets) is a follow-up, not a
  blocker. The workflow code references the existing secret names
  unchanged.

## Follow-ups

- Rename the `semantic-release-agent-auth` GitHub App and rotate the
  repo secrets to `RELEASE_APP_ID` / `RELEASE_APP_PRIVATE_KEY`. New
  issue, separate PR.
- Per-package release trains (#275) — the YAML schema is ready; the
  workflow needs the per-package fan-out.
- If the `main` ruleset blocks workflow-token PRs, switch the
  release-PR opener identity to the App. New issue if and when the
  block surfaces.
