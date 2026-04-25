<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: YAML-driven release workflow; decommission semantic-release (#296)

Closes #296. Sub-issue of #289 (clean PR-to-commit + release flow).
Builds on #295 (PR #303) which shipped the `version_logic` library and
the `changelog/@unreleased/*.yml` schema, and on #290 (PR #302) which
introduced the Palantir-style PR title prefixes and `==COMMIT_MSG==`
block lint.

## Summary

Replace `semantic-release` with a custom GitHub-Actions release flow
driven by `changelog/@unreleased/pr-*.yml` files:

1. `release-pr.yml` opens (or updates) a release PR on every push to
   `main` while at least one `@unreleased/` entry exists.
2. The maintainer reviews the release PR through the same gate as any
   other change. Merging it tags `vX.Y.Z` and creates a GitHub Release
   from the *moved* YAMLs (the same content the PR previewed).
3. The existing `release-publish.yml` (artefact build + SBOM + cosign
   signing + SLSA L3 provenance, triggered by the new tag push) keeps
   running unchanged so the supply-chain story doesn't regress.

The version computation is delegated to the shared `version_logic`
library from #295 — there is no second source of truth for the bump
table or the `release-as` invariant.

## Out of scope (deferred)

- Per-package release trains (#275). YAML carries `packages:` but the
  inference here ignores it and applies a single workspace-root tag,
  matching the current single-train model documented in ADR 0035.
- The `task changelog-add` CLI helper (#297).
- Bot-mediated authoring via `==CHANGELOG_MSG==` markers (#298).
- The merge bot that auto-pastes `==COMMIT_MSG==` into the squash
  dialog (#291). Until it lands the release maintainer pastes the
  block by hand, same as every other PR.

## Design verification

### Architecture decision

A new ADR — `design/decisions/0040-yaml-driven-release-workflow.md` —
records the architectural switch from semantic-release (ADR 0026) to
the YAML-driven release-PR flow. ADR 0026 stays accepted but is
explicitly superseded by 0039 on the autorelease driver. The carry-
over decisions from ADR 0016 (keyless cosign, SPDX SBOM via Syft,
setuptools-scm runtime version) and the SLSA-L3 chain from ADR 0020
are unaffected.

### Decision log

Non-obvious calls captured in the ADR and the PR's `==COMMIT_MSG==`:

- **Workflow naming** — keep `release-publish.yml` reserved for the
  artefact build + sign step (it still triggers on `push: tags: ['v*']`). The new PR-merge handler lives in `release-tag.yml`. The
  alternative — renaming `release-publish.yml` to
  `release-artifacts.yml` and taking over the name for the new
  handler — would invalidate SECURITY.md's verification recipe for
  any release that hasn't shipped yet (the recipe pins
  `--certificate-identity` to the workflow path). Keeping the artefact
  workflow's name fixed avoids touching the supply-chain trust
  vocabulary. The issue body's wording "release-publish.yml runs on
  release-PR merge" is treated as describing the *step* rather than
  the *file name*, since the issue does not contemplate the existing
  artefact pipeline that already owns that filename.
- **Branch naming** — `release/<X.Y.Z>`. Lets the publish workflow
  filter by `head.ref` regex without parsing the title (cheaper and
  less ambiguous than reading the merge subject).
- **Release-PR title** — `chore(release): <X.Y.Z>`. `chore` is in
  the `pr-lint.yml` allowlist (#290), and the prefix matches the
  historic Conventional-Commits convention so existing tooling (e.g.
  the `verify-standards.sh` `task release` requirement, the
  CHANGELOG style) keeps reading.
- **`==COMMIT_MSG==` block** — the release-PR's auto-generated body
  *does* include a `==COMMIT_MSG==` block. Its content is the
  rendered release-notes summary. Lines wrap at \<=72 chars. No
  bullet lists / headings inside the block (the renderer emits prose
  paragraphs grouped by type; markdown lists go in the Review notes
  section). One `Closes #N` trailer per moved YAML's referenced
  issue is *not* added — the YAMLs themselves carry the linking
  metadata in their `links:` field, surfacing via the rendered notes
  rather than via git trailers.
- **Release-PR `changelog-lint` interaction** — release PRs *delete*
  every `@unreleased/*.yml` (renaming them under `<X.Y.Z>/`) rather
  than adding a new one. The lint's "file presence" check would fail
  closed on this. The fix is to skip the lint when
  `pull_request.head.ref` matches `^release/[0-9]+\.[0-9]+\.[0-9]+$`,
  and to widen the schema check to tolerate the moved-out state. The
  bypass is added to `changelog-lint.yml` rather than baked into
  `lint.py` so the bypass surface stays visible at the workflow level.
- **`pr-lint` interaction** — the rendered release notes need to
  satisfy the `==COMMIT_MSG==` validator. The renderer wraps lines,
  uses prose paragraphs, and emits a single `Signed-off-by:` trailer
  for the workflow's bot identity. No bullet lists, no markdown
  headings, no checkboxes. The `pr-title` job already accepts
  `chore(release): X.Y.Z` (it accepts any `chore` PR with optional
  scope).
- **Bot identity for the release PR** — first cut uses the default
  `GITHUB_TOKEN`. If the `main` branch ruleset blocks PRs opened by
  the workflow token (or blocks them from later being merged through
  the gate), the follow-up is to mint a short-lived token from the
  existing `semantic-release-agent-auth` GitHub App (renamed to
  `release-pr-agent-auth` in a separate PR — see Follow-ups).
  Reusing the App's secrets keeps the rotation story unchanged.
- **Idempotency on re-run** — the workflow always recomputes the
  next version from the *current* set of `@unreleased/` YAMLs. If
  the version has not changed since the last run, it force-pushes
  the same `release/<X.Y.Z>` branch with the refreshed CHANGELOG
  diff. If the version *has* changed (e.g. a new YAML added a feature
  on top of fixes; or a `release-as` override was added), the
  previous `release/<old>` PR is closed and a fresh
  `release/<new>` PR is opened. The closed PR's branch is deleted so
  the workflow does not accumulate stale refs.
- **Tag identity** — the tag is created by `release-tag.yml` on the
  PR-merge commit using the App-token path (so the tag push fires
  the existing `release-publish.yml` artefact workflow). The default
  `GITHUB_TOKEN`'s tag pushes do *not* fire downstream `on: push: tags:` triggers, which would silently break the SLSA chain. This is
  the same constraint that drove ADR 0026's App-token requirement.

### Threat model

No new attack surfaces. The release flow gains a maintainer-merge
gate it didn't have before, which strictly improves on the previous
"any push to main can cut a release" story. The supply-chain trust
boundary (ADRs 0016 + 0020) is unchanged: the artefact-build workflow
still runs on `push: tags: ['v*']`, still produces SLSA-L3
provenance, still signs with keyless cosign. The release-tag
workflow only takes the inputs from the *moved* YAMLs (already on
main, already reviewed) — it cannot inject new content.

The only sensitive surface added is the App's installation token
used by `release-tag.yml` to push the tag. This was already in scope
under ADR 0026 (the same token pushed `chore(release):` commits and
tags in the old flow). Token lifetime stays bounded to the workflow
run.

### QM / SIL compliance

This is tooling, not service code. The QM gate from
`.claude/instructions/design.md` (verify-design, verify-function-tests)
does not apply to `scripts/changelog/` or release workflows. The
existing `scripts/changelog/test.sh` covers the new
`build_release.py` module under the same regime as `version_logic.py`

- `lint.py`.

## Implementation

### New files

- `.github/workflows/release-pr.yml` — opens or updates the release
  PR on every push to `main`.
- `.github/workflows/release-tag.yml` — runs on the release-PR merge,
  tags `vX.Y.Z`, creates the GitHub Release. Triggers
  `release-publish.yml` (the existing artefact workflow) via the
  tag-push.
- `scripts/changelog/build_release.py` — Python module + CLI:
  - `compute_release(...)` → returns `ReleasePlan(version, moves, changelog_section, release_notes)`.
  - `apply_release(...)` → executes the moves and rewrites
    `CHANGELOG.md`.
  - `render_release_notes(...)` → produces the prose used in both
    the release-PR body and the GitHub Release body.
  - `cli main` for the workflow YAML to invoke as `python scripts/changelog/build_release.py …`.
- `scripts/changelog/tests/test_build_release.py` — unit tests
  covering: empty `@unreleased/` skips, single-feature → minor on
  0.x, single-break → minor on 0.x but major on 1.x, conflicting
  `release-as` raises, valid `release-as` honoured, file moves are
  computed but not executed by the pure compute step, the rendered
  notes satisfy `validate-commit-msg-block.py`'s rules.
- `design/decisions/0040-yaml-driven-release-workflow.md` — the ADR.
- `changelog/@unreleased/pr-<N>-yaml-driven-release-workflow.yml` —
  the `feature` entry for this PR (filename embeds the PR number,
  filled in once `gh pr create` returns it).

### Removed files

- `.github/workflows/release.yml` — semantic-release driver.
- `.releaserc.mjs` — semantic-release config.
- `package.json`, `package-lock.json` — only the semantic-release
  toolchain lived under npm.
- `scripts/lib/semver.sh` and `tests/test_release_semver.py` — the
  bash bump library and its tests, only used by the old
  `scripts/release.sh`.
- The npm entry in `.github/dependabot.yml` (the only npm consumer
  was semantic-release).
- The `.releaserc.mjs`, `package-lock.json`, `package.json` entries
  in `REUSE.toml`.

### Repurposed files

- `scripts/release.sh` — rewritten as a thin wrapper around
  `gh workflow run release-pr.yml`, so `task release` (which is
  required by `verify-standards.sh`) keeps working. Keeps the
  CONTRIBUTING entry point alive and gives a manual escape hatch
  when a maintainer needs to force a release-PR refresh.
- `Taskfile.yml` `release` task — desc updated to reflect that it
  triggers the workflow rather than cutting locally.
- `CONTRIBUTING.md` § Release process — rewritten end-to-end:
  - "Default path" now describes the release-PR + merge flow.
  - "Break-glass path: `task release`" describes the workflow-trigger
    wrapper instead of the local-tag flow.
  - The semantic-release App registration steps are dropped; the App
    is renamed (or a new one minted) in the follow-up issue.
- `.claude/instructions/release-and-hygiene.md` — the "Release task"
  bullet is updated to describe the new workflow shape.
- `.github/workflows/changelog-lint.yml` — bypass for
  `head.ref =~ ^release/.*` so the release-PR doesn't trip the
  file-presence check.
- `.github/workflows/pr-lint.yml` — no change strictly required
  (the rendered notes obey the validator); a bypass for
  `release/*` is *not* added so the validator continues to gate the
  release-PR's body content. If the renderer slips a malformed line
  in, the lint catches it before the maintainer merges.

### `release-pr.yml` flow

01. Trigger: `push: { branches: [main] }`. Skip on the merge commit
    that *closed* a release-PR by pattern-matching the head commit
    subject (avoid an immediate re-open while the merge commit's
    `@unreleased/` directory is empty — the early-exit on "no entries"
    already handles this, but a subject filter is the secondary
    defense).
02. Checkout `main` with full history.
03. Resolve the current version: `git describe --tags --abbrev=0 --match 'v*'`. Falls back to `0.0.0` when no tag exists.
04. Run `python scripts/changelog/build_release.py compute` which:
    - Parses every `changelog/@unreleased/pr-*.yml` via
      `version_logic.parse_entry_file`.
    - Calls `version_logic.validate_release_as(entries, current)`.
    - Calls `version_logic.infer_next_version(current, entries)`.
    - Calls `version_logic.apply_release_as(inferred, entries)`.
    - Renders the new CHANGELOG section and the release-notes body.
    - Emits a JSON plan on stdout and the rendered files into a
      workspace tmpdir.
05. Exit cleanly if the plan is empty (no entries → no PR to open).
06. Check whether `release/<X.Y.Z>` already exists on origin. If yes,
    reset it to the new computed state. If no, create it.
07. List existing open PRs whose head ref matches `release/.*`. If
    the version differs from `<X.Y.Z>`, close them and delete their
    branches (the new PR supersedes them).
08. Apply the moves on the release branch:
    - `git mv changelog/@unreleased/pr-*.yml changelog/<X.Y.Z>/`.
    - Overwrite `CHANGELOG.md` with the rendered content.
    - Commit with `chore(release): <X.Y.Z>` (signed off as the App
      identity).
09. Push the branch (force-with-lease so a re-run cleanly overwrites
    the previous attempt).
10. Open the PR if absent; update its title + body if present. Body
    contains the `==COMMIT_MSG==` block (rendered notes), a
    `## Review notes` section pointing at the moved YAMLs, and the
    standard issue links.

### `release-tag.yml` flow

1. Trigger: `pull_request: { types: [closed], branches: [main] }`.
2. Filter steps:
   - `pull_request.merged == true`.
   - `pull_request.head.ref =~ ^release/[0-9]+\.[0-9]+\.[0-9]+$`.
   - `pull_request.title =~ ^chore\(release\): [0-9]+\.[0-9]+\.[0-9]+$`.
3. Extract `<X.Y.Z>` from the head ref (the title regex is the
   secondary defense).
4. Mint an installation token via `actions/create-github-app-token`
   so the tag push fires `release-publish.yml`.
5. Re-render the release notes from the moved YAMLs at `<X.Y.Z>/`
   (using the same `build_release.py` module so the body matches the
   PR preview byte-for-byte).
6. Sign and push `v<X.Y.Z>` on the merge commit.
7. `gh release create v<X.Y.Z>` with the rendered body.

### `build_release.py` API

```python
@dataclass(frozen=True)
class FileMove:
    src: Path  # changelog/@unreleased/pr-N-x.yml
    dst: Path  # changelog/<X.Y.Z>/pr-N-x.yml

@dataclass(frozen=True)
class ReleasePlan:
    next_version: str        # X.Y.Z (no v prefix)
    current_version: str
    entries: tuple[ChangelogEntry, ...]
    moves: tuple[FileMove, ...]
    changelog_section: str   # the rendered ## [X.Y.Z] section
    release_notes: str       # the prose for the PR body / GH Release

def compute_release(repo_root: Path, current_version: str) -> ReleasePlan | None: ...
def apply_release(plan: ReleasePlan, repo_root: Path) -> None: ...
def render_release_notes(entries: Sequence[ChangelogEntry], version: str) -> str: ...
def render_changelog_section(entries, version, date) -> str: ...
```

The grouping order — `break` → `feature` → `improvement` → `fix` →
`deprecation` → `migration` — is encoded as a module-level constant
`SECTION_ORDER` so the test suite can assert it without re-deriving
the list.

### Naming and types (coding-standards.md)

- Functions are verbs (`compute_release`, `render_release_notes`,
  `apply_release`); the dataclass is `ReleasePlan` (a noun).
- Versions are `str` of the canonical `X.Y.Z` form throughout — the
  `_parse_semver` helper from `version_logic` is reused so callers
  get a single failure mode for malformed input.
- File moves are typed via `FileMove`, not raw `(src, dst)` tuples,
  matching the project's "no raw tuples for structured keys" rule.

### Tests

Coverage targets (mirrors `version_logic.py`'s coverage gate):

- `compute_release` empty `@unreleased/` returns `None`.
- `compute_release` honours `release-as` when present.
- `render_release_notes` groups by `SECTION_ORDER`.
- `render_release_notes` output passes
  `validate-commit-msg-block.py`'s line-width + no-markdown rules
  (the test re-imports the validator and runs it over the rendered
  body).
- `apply_release` performs the moves and rewrites `CHANGELOG.md`
  prepending the new section.
- `apply_release` is idempotent within a temp git repo — running
  twice with the same plan produces no extra diff (so a workflow
  retry doesn't double-write the section).

### Workflow fixture / smoke

A short bash fixture under `.github/workflows/tests/release-fixtures/`
is *not* added — the unit tests on `build_release.py` cover the
behaviour, and the workflow YAML's branching is too thin to warrant
a fixture suite. The workflow's first real run on `main` is the
acceptance test; the rollback path is "delete the release-PR branch
and try again".

## Self-review checklist (post-implementation)

Run before pushing:

- `grep -RIn 'semantic-release\|releaserc\|@semantic-release' -- exclude-dir=node_modules .` returns no results outside CHANGELOG.md
  history entries and the existing ADR 0026 / 0035 retrospective
  references.
- `grep -RIn 'package\.json\|package-lock\.json' --exclude-dir= node_modules .` returns no live references (only CHANGELOG history
  and the deleted REUSE.toml entries' diff context).
- `task check` passes.
- `task changelog:test` passes (covers `version_logic` + `lint` + new
  `build_release`).
- `scripts/verify-standards.sh` passes (`task release` is still in
  Taskfile.yml; npm ecosystem requirement is gone now that
  `package.json` is removed).
- `scripts/reuse-lint.sh` passes after stripping the dropped paths
  from `REUSE.toml`.
- The release-PR's auto-generated body, fed through
  `scripts/validate-commit-msg-block.py`, passes.

## Apply post-implementation standards review

(per `.claude/instructions/plan-template.md`)

- **coding-standards.md** — verb names on procedures; types on every
  module-level function; no raw tuples for structured keys (use
  `FileMove`, `ReleasePlan`); no implicit units.
- **service-design.md** — the workflow files are CI tooling, not
  services; XDG paths and HTTP gates do not apply. The version-
  inference call goes through `version_logic` (single source of
  truth), not duplicated.
- **release-and-hygiene.md** — `task release` still exists.
  CONTRIBUTING.md § Release process is rewritten. CHANGELOG.md gets
  its REUSE annotation updated to drop the semantic-release reference
  in the explanatory comment.
- **testing-standards.md** — `build_release.py` exposes a public
  surface (`compute_release`, `apply_release`, `render_*`); tests
  exercise that surface only.
- **tooling-and-ci.md** — every new workflow uses
  `setup-toolchain` for uv + python; third-party actions stay
  SHA-pinned.

## Closing scope

- `Closes #296` — the issue itself.
- `Closes #215` — the signed-release-commit work is obviated:
  there's no longer a bot-pushed release commit. The release commit
  on the release branch is the maintainer's reviewed merge commit,
  which lands through the standard signed-commit ruleset.

## Follow-ups (do not block this PR)

- Rename or replace the `semantic-release-agent-auth` GitHub App
  with `release-pr-agent-auth` (or merge into a single
  `release-bot-agent-auth`). Track in a new issue once the
  release-tag workflow lands and we know which App identity actually
  needs to push tags. Until then the App keeps its current name and
  secrets — the workflow code references `SEMANTIC_RELEASE_APP_*`
  unchanged.
- Per-package release trains (#275) — the YAML's `packages:` field
  is parsed but ignored at version-inference time.
