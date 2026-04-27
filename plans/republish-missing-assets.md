<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Re-publish missing release assets for v0.11.0..v0.15.3

Refs #372. Adds a `workflow_dispatch` trigger to
`release-publish.yml` so a maintainer can re-run the publish pipeline
against an existing tag, plus `SECURITY.md` notes for the tag ranges
where the documented verification recipe will not match the assets on
the release page. The actual `gh workflow run` invocations against
the 12 affected tags are post-merge operational follow-up — this PR
ships only the workflow surface change and the SECURITY.md notes.
Issue #372 stays open across the post-merge ops.

## Context

PR #325 added a post-publish asset-count smoke test to
`release-publish.yml` and a PR-time build dry-run in
`release-dryrun.yml` (now hardened to per-package counts in PR #393).
That smoke test surfaced a silent regression: every release between
the workspace split (PR #270) and PR #324 (per-package wheels +
venv install) silently produced a wheel-less release. Specifically:

- **`v0.11.0..v0.15.3`** (12 tags) — post-workspace-split, but each
  release was tagged before the per-package build was wired up. The
  `release-publish.yml` jobs ran but uploaded zero or partial assets;
  the new smoke test would have failed all 12 had it existed
  pre-#325.
- **`v0.6.0..v0.10.0`** (5 tags) — pre-workspace-split, single-package
  shape. The verification recipe in `SECURITY.md` enumerates
  `agent_auth_common`, `gpg_bridge`, `gpg_cli`, etc. — none of those
  packages existed pre-#270. The recipe will not match these tags
  even if the assets are technically present.
- **`v0.16.0`** — first release after PR #324 landed. The per-package
  build ran and uploaded the correct asset shape, but every wheel and
  sdist is versioned `0.0.0+unknown` instead of `0.16.0`. The
  verification recipe builds filenames like
  `agent_auth-0.16.0-py3-none-any.whl`, which do not exist on the
  release. Tracked separately as #408; this PR adds only the SECURITY.md
  note pointing readers there.

This issue (#372) is the cleanup pass for the 12-tag gap. The
acceptance criteria call for either re-running publish against each
tag or cutting a patch release; re-running publish is preferred
(keeps tag identity stable, no patch-release noise in `CHANGELOG.md`).
Today `release-publish.yml` only triggers on `push: tags: ["v*"]`, so
once a tag is pushed there is no in-band way to re-run the workflow
against it. This PR adds the `workflow_dispatch` trigger that closes
that gap.

## Sources

- **`.github/workflows/release-publish.yml`** — current workflow.
  `on: push: tags:` trigger; `${{ github.ref }}` and
  `${{ github.ref_name }}` references on lines 25, 140, 209.
- **`.github/workflows/release-dryrun.yml`** — sibling workflow
  using the same `scripts/build-release-artifacts.sh` build script.
  Trigger pattern not directly mirrorable (PR-time-only) but the
  concurrency-group fallback pattern (`event.pull_request.number || github.ref`) is informative.
- **`docs/release/release-bot-setup.md`** — confirms the App's
  `Contents: Read & write` permission covers the
  `gh release upload` call regardless of trigger type. The
  `actions/create-github-app-token` step does not gate on
  `github.event_name`.
- **`SECURITY.md` § *Supply-chain artifacts*** (lines 392–548) —
  the verification recipe consumers run against a release tag.
  Lines 451–469 enumerate the per-package wheels + sdists; this is
  where the per-tag-range applicability notes live.
- **Issue #372 body** — acceptance: re-run publish against each
  affected tag (preferred over cutting a patch); update SECURITY.md
  with a one-line note for any tag where the recipe will not work.
- **Issue #408** — `v0.16.0` versioning bug. Out of scope here; the
  SECURITY.md note links to #408 for context.

## Workflow change — `release-publish.yml`

### Trigger

Current:

```yaml
on:
  push:
    tags: ["v*"]
```

After:

```yaml
on:
  push:
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      tag:
        description: "Tag to (re-)publish, e.g. v0.13.0. Must already exist on origin."
        required: true
        type: string
```

`workflow_dispatch` only fires off the workflow file present on the
default branch (`main`), so once this PR merges every existing tag
becomes re-publishable from the Actions tab or via
`gh workflow run release-publish.yml -f tag=<TAG>`. The input is
free-form; GitHub does not validate that `tag` exists on origin
because the actual existence check happens at the
`actions/checkout` step (a non-existent ref fails the checkout
loudly).

### `${{ github.ref* }}` reference adaptation

Three references in `release-publish.yml` consume the tag and need
the `inputs.tag || github.ref_name` fallback. Enumerated:

1. **Line 25 — `concurrency.group`**:
   `release-publish-${{ github.ref }}`. Used to serialise concurrent
   publish runs against the same ref. For `push: tags`,
   `github.ref` is `refs/tags/vX.Y.Z`; for `workflow_dispatch`,
   `github.ref` is `refs/heads/main` (the default branch the
   dispatch fires from). A re-publish against `vX.Y.Z` should
   share the concurrency group with the original tag-push run so a
   maintainer who fires a re-publish while the original is still
   running gets the queueing behaviour the group promises.
   Adaptation: `release-publish-${{ inputs.tag || github.ref_name }}`.
   `github.ref_name` is `vX.Y.Z` for tag pushes (the bare name, no
   `refs/tags/` prefix), so the post-adaptation group key is
   `release-publish-vX.Y.Z` for both triggers.
2. **Line 140 — `Upload artefacts to GitHub release` env `TAG`**:
   `${{ github.ref_name }}`. Threaded into
   `gh release upload "${TAG}" ...`. Adaptation:
   `${{ inputs.tag || github.ref_name }}`.
3. **Line 209 — `Verify expected release assets are uploaded` env
   `TAG`**: same shape as line 140, threaded into
   `gh release view "${TAG}" --json assets`. Adaptation:
   `${{ inputs.tag || github.ref_name }}`.

Both `TAG` env values are interpolated into the `env:` block (not
into `run:` directly), so the existing pattern already protects
against the CodeQL `js/actions/command-injection` finding noted in
the conventions. The adaptation preserves that safety: `inputs.tag`
flows through `env:`, then into the shell as `${TAG}`.

### `actions/checkout` ref

Line 37 (publish job) and line 201 (verify-assets job) both run
`actions/checkout@v6`. Today the publish job uses `fetch-depth: 0`
without an explicit `ref:`, so `actions/checkout` defaults to
`github.ref` — for tag pushes this is the tag, for
`workflow_dispatch` it is the default branch (`main`). For a
re-publish to bind the SLSA provenance + cosign signatures to the
tag's commit (not `main`'s tip), the publish job must check out the
input tag explicitly. Adaptation:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
  with:
    fetch-depth: 0
    ref: ${{ inputs.tag || github.ref }}
```

`github.ref` is correct for the `push: tags` path because it
resolves to `refs/tags/vX.Y.Z`. For `workflow_dispatch` the bare
tag name `vX.Y.Z` (from `inputs.tag`) is a valid ref expression
that `actions/checkout` resolves against the `tags/` namespace.

The `verify-assets` job (line 201) reads `packages/<svc>/pyproject.toml`
to count workspace members for the asset-count assertions. The
commit at the tag will give a per-tag-correct workspace member
count, which is what the assertions need. Adaptation: same
`ref: ${{ inputs.tag || github.ref }}`.

### `provenance` job's reusable workflow `@v2.1.0`

Line 175 references the SLSA generator reusable workflow at
`@v2.1.0`. This is a self-introspecting tag (the workflow embeds
its own `@ref` in the provenance) and unrelated to the publish
ref; no change needed.

### `slsa-framework/slsa-github-generator` subject set

The `hashes` output (line 35) is fed to the generator via the
`needs.publish.outputs.hashes` parameter at line 177. The hashes
come from `dist/`, which `scripts/build-release-artifacts.sh`
writes; the build runs against whatever ref the publish job
checked out. With the checkout-ref adaptation above, the build
runs against the tag, the hashes correspond to the tag's
artefacts, and the SLSA provenance binds correctly to the tag.

### App-token step

Lines 130–135 mint a `RELEASE_BOT_*` installation token. The App's
`Contents: Read & write` permission gates the API surface, not the
trigger type — `workflow_dispatch`-triggered runs mint tokens
exactly the same way. `docs/release/release-bot-setup.md` does not
mention `workflow_dispatch` because the App pre-dates it, but the
permission model covers it transparently.

### What does **not** change

- `permissions:` block — already `contents: write` and
  `id-token: write`; both required regardless of trigger.
- `concurrency.cancel-in-progress: false` — protect mid-release
  state on both triggers.
- The build / sign / SBOM / hash steps — they consume `dist/`,
  which the checkout-ref adaptation populates correctly.
- `release-dryrun.yml` and every other workflow — untouched.

## SECURITY.md edits

The `## Supply-chain artifacts` section currently does not call
out per-tag applicability of the verification recipe. Two notes
are added, scoped tightly so the rest of the section is
untouched. Placement: directly after the verification-recipe code
block, before `### Trust boundary and residual risks`, as a new
subsection or a single paragraph block (whichever matches
surrounding heading style).

Proposed wording (tight, tag-range-scoped, links to issues):

> **Tag applicability.** The recipe enumerates the workspace
> packages that exist on `main` today. It will not match every
> historical release tag:
>
> - **`v0.6.0..v0.10.0`** — pre-workspace-split releases. These
>   tags ship a single `agent_auth-X.Y.Z-py3-none-any.whl` (no
>   per-package layout); the per-package PACKAGES loop in the
>   recipe will not find them. Install the legacy wheel directly
>   if needed, or upgrade to `v0.11.0` or later.
> - **`v0.11.0..v0.15.3`** — post-workspace-split, but the
>   release-publish pipeline silently produced incomplete asset
>   sets (tracked as #372). Re-publish is in progress; until
>   each affected release page enumerates the full per-package
>   asset set, the recipe's `cosign verify-blob` and
>   `slsa-verifier verify-artifact` steps will fail at the
>   missing-asset-download step.
> - **`v0.16.0`** — wheels and sdists are present in the
>   per-package layout but versioned `0.0.0+unknown` instead of
>   `0.16.0` (tracked as #408). The recipe builds filenames
>   like `agent_auth-0.16.0-py3-none-any.whl`, which do not
>   exist on this release. Use `v0.16.1` (or later) once shipped.

Exact heading style and bullet-vs-paragraph format are decided at
implementation time to match surrounding section conventions.

## Maintainer test plan

`workflow_dispatch` only fires off the default-branch copy of the
workflow file, so this PR's change is **not** dispatchable
pre-merge. The test plan is:

1. **Pre-merge.** Confirm the YAML is well-formed and the
   `${{ github.ref* }}` adaptation is exhaustive by running
   `grep -n 'github\.ref\|inputs\.tag' .github/workflows/release-publish.yml`
   against the PR branch; expect exactly the three pre-adaptation
   sites covered, each now using the
   `${{ inputs.tag || github.ref_name }}` (or `github.ref`)
   fallback. Confirm `release-dryrun.yml` is untouched
   (`git diff main...HEAD -- .github/workflows/release-dryrun.yml`
   is empty).

2. **Post-merge smoke (orchestrator runs this).** Pick an existing
   tag whose release page is already correct (e.g. `v0.16.0` —
   the assets are present even if mis-versioned, or any future
   green release). From the Actions tab, run "Release Publish"
   with `tag=<TAG>`, or:

   ```bash
   gh workflow run release-publish.yml -f tag=<TAG>
   ```

   Expected: the run goes green and the release-page asset set
   is unchanged (uploads use `--clobber`, so re-running is
   idempotent for an already-correct release).

## Post-merge operational follow-up (orchestrator checklist)

After this PR merges, run `gh workflow run release-publish.yml -f tag=<TAG>` against each of the 12 post-split-but-empty tags. The
assets-upload step uses `--clobber` so re-running is safe even
against a release page that already has some (but not all)
assets. Each invocation goes through the full sign / SBOM / SLSA
provenance chain.

```bash
for TAG in \
  v0.11.0 \
  v0.12.0 v0.12.1 v0.12.2 \
  v0.13.0 v0.13.1 \
  v0.14.0 v0.14.1 \
  v0.15.0 v0.15.1 v0.15.2 v0.15.3
do
  gh workflow run release-publish.yml -f tag="${TAG}"
done
```

After every re-publish run completes green and the
`verify-assets` job confirms the asset count, close #372.

The pre-split range (`v0.6.0..v0.10.0`) and `v0.16.0` are **not**
re-publishable through this workflow — pre-split releases use a
different build shape, and `v0.16.0`'s versioning bug needs the
fix in #408 before re-publishing makes sense. Their handling is
captured by the SECURITY.md notes and (for v0.16.0) by #408.

## Skipped plan-template steps

- **Verify implementation against design doc** — N/A. ADR 0044
  covers the per-package distribution model; this PR adds an
  alternate trigger path through the same publish pipeline,
  not a new asset shape.
- **Threat model** — partial. `workflow_dispatch` is restricted
  to actors with `write` permission on the repo (default GitHub
  behaviour); the App-token mint and `gh release upload` calls
  are unchanged from the `push: tags` path. `--clobber`
  semantics mean a malicious dispatch could re-upload assets
  against a tag, but the OIDC-bound cosign signatures and the
  SLSA-generator-runner identity continue to bind to the dispatch
  run, and any consumer that uses the re-published-tag recipe in
  SECURITY.md (or the primary tag-bound recipe) detects the
  mismatch on `cosign verify-blob` or `slsa-verifier`. Note that
  re-published assets carry an identity bound to
  `refs/heads/main`, not to the historical tag — path (a)
  (closing the asset-count gap) is functional, but consumers must
  use the `### Re-published tag applicability` recipe in
  SECURITY.md to verify them; the primary tag-bound recipe will
  fail closed at the signature check. No new attack surface.
- **PIR** — N/A; not a vulnerability remediation.
- **ADRs** — N/A; the trigger addition is a workflow surface
  change. ADR 0044 covers the asset shape; ADR 0026 covers the
  release-App identity. Neither needs an amendment.
- **Cybersecurity standard / QM-SIL** — N/A for a
  workflow-trigger change.
- **Coding / service-design / testing standards** — N/A; no
  Python or HTTP surface touched.
- **Release and hygiene standards** — applicable. Hand-author a
  user-visible changelog entry (operators gain a re-publish
  surface; consumers gain recipe-applicability docs). Apply.
- **Tooling and CI standards** — applicable. `treefmt` /
  `actionlint` remain green. Apply.

## Acceptance

- `release-publish.yml` accepts `workflow_dispatch` with a `tag`
  input and threads `inputs.tag || github.ref_name` (or
  `github.ref`) through every tag-consuming reference.
- `SECURITY.md` § *Supply-chain artifacts* documents tag-range
  applicability for `v0.6.0..v0.10.0`, `v0.11.0..v0.15.3`, and
  `v0.16.0`.
- No other workflows are touched.
- A user-visible changelog entry is hand-authored.
- `#372` stays open across post-merge re-publish ops; the
  orchestrator closes it after the 12-tag re-publish loop
  succeeds.
