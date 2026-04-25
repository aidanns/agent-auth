<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan 0002 — Merge bot pastes `==COMMIT_MSG==` as squash body (#291)

Sub-issue of #289. Replaces the maintainer-paste step from #290 with
a GitHub Action that, on merge, extracts the `==COMMIT_MSG==` block
from the PR body and calls `PUT /repos/.../pulls/{n}/merge` with
`merge_method: squash`, `commit_title: <PR title>`, and
`commit_message: <extracted block>`.

## Scope

- New workflow `.github/workflows/merge-bot.yml` triggered on
  `pull_request: labeled` (label name == `automerge`) AND
  `check_suite: completed` (sticky-label retry once the last check
  goes green).
- Reusable Python entrypoint `scripts/extract-commit-msg-block.py`
  that exposes an `extract(body: str) -> str` library function on
  top of the existing `scripts/validate-commit-msg-block.py` parser
  (no regex re-implementation in the workflow).
- Soft pre-merge sanity check: `==COMMIT_MSG==` body must contain a
  `Signed-off-by:` trailer (DCO). Surfaced both in the merge bot
  (hard-fail comment) and in `pr-lint.yml` as an extension to the
  existing block validator (hard-fail) so contributors learn before
  the bot rejects.
- Maintainer setup doc `docs/release/merge-bot-setup.md` covering App
  creation, secret names, `main` ruleset bypass-actor configuration,
  and the post-rollout `squash_merge_commit_message` flip.
- ADR `design/decisions/0038-merge-bot-via-github-app.md` capturing
  the App-identity + label-trigger + refuse-on-lint-fail decisions.
- `CONTRIBUTING.md` and `docs/release/rollout-pr-template.md`
  updates to replace the manual paste step with the `automerge`
  label.
- `changelog/@unreleased/pr-<N>-merge-bot-commit-msg.yml` (`type: feature`).
- New fixture coverage for the extractor (the existing fixtures
  already exercise the parser; add a small unit test that exercises
  `extract()` against `valid-template-default.md` and asserts the
  HTML-comment scaffolding is preserved verbatim — the bot must
  paste the block as-is).

## Out of scope

- Creating the GitHub App itself (maintainer-side, documented).
- Removing native squash-merge from repo settings — that's a
  follow-up flip after a release cycle of bot-mediated merges.
- `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` enforcement — #298.
- `.releaserc.mjs` decommissioning — #296.
- Per-package release trains — #275.

## Design and verification

- **Verify implementation against design doc** — N/A; this is a
  release-mechanics change, not a service surface. Design impact is
  captured in the ADR.
- **Threat model** — the bot calls a privileged merge endpoint on
  behalf of a GitHub App. Considered failure modes:
  - *Malicious PR body* — `commit_message` is rendered as commit
    bytes, not a shell or template. The validator rejects markdown
    and unknown trailers; the merge call passes the string verbatim
    to the GitHub API. No code-execution surface.
  - *Workflow-trigger loop* — the bot's own success comment must
    not re-trigger the workflow. The workflow gates on
    `pull_request: labeled` and `check_suite: completed` only, not
    `issue_comment`, so a bot-authored comment cannot retrigger it.
  - *App-token theft* — the App token is minted in-workflow via
    `actions/create-github-app-token` and is short-lived (≤ 1h).
    The App is scoped to a single repo with `pull_requests: write`,
    `contents: read`, `metadata: read`. No `id-token: write` or
    write-to-Contents — the bot cannot push commits, only call the
    merge endpoint.
  - *Concurrent triggers (label + check-suite race)* — GitHub's
    `merge` endpoint is idempotent on already-merged PRs (returns
    405 with a documented error code); the workflow treats that
    as a no-op and exits cleanly.
- **Post-incident review (PIR)** — N/A; not a vulnerability fix.
- **Architecture Decision Records** — write
  `design/decisions/0038-merge-bot-via-github-app.md` capturing:
  (a) why a dedicated GitHub App rather than `GITHUB_TOKEN` or a
  PAT or the existing semantic-release App,
  (b) why an `automerge` label rather than auto-on-mergeable or
  `gh pr merge --auto --squash`,
  (c) refuse-on-lint-fail semantics (no fallback to BLANK),
  (d) DCO trailer must be inline in the `==COMMIT_MSG==` block
  rather than added by the bot (the bot authors no commit).
- **Cybersecurity standard compliance** — N/A; out of scope for
  release-mechanics tooling. The App's least-privilege scoping is
  the relevant control and is documented in the setup doc.
- **Verify QM / SIL compliance** — N/A; SIL is product-side.

## Implementation

01. ADR `design/decisions/0038-merge-bot-via-github-app.md`.

02. Refactor `scripts/validate-commit-msg-block.py` minimally to
    expose two pure functions the bot reuses without redefining
    the regex:

    - `extract_block(body: str) -> str` — already exists; document
      it as the public API.
    - `validate(body: str) -> None` — already exists.
      No behaviour change to the validator's CLI.

03. Add `scripts/extract-commit-msg-block.py` — a thin CLI wrapper
    that imports `validate_commit_msg_block.extract_block` (via
    sibling-script `sys.path` trick already used by
    `scripts/changelog/lint.py`) and prints the extracted block to
    stdout. Used by the merge-bot workflow to stage the body for
    the API call. Why a separate CLI rather than calling the
    validator: the validator runs the full lint and exits 1 on
    bad bodies. The extractor exits 0 and prints; the bot decides
    what to do with the extracted text. Both share the same parser.

04. Add a unit test `tests/test_extract_commit_msg_block.py` (root
    `tests/` per existing workspace-wide test layout — same place
    as `tests/test_release_semver.py` etc.) that:

    - Reuses `.github/workflows/tests/pr-lint-fixtures/valid-*.md`
      to assert `extract_block(body)` returns the contents between
      the markers verbatim (HTML comments preserved — the bot must
      paste exactly what the contributor authored).
    - Asserts a missing-block input raises `ValidationError`.

05. Extend the validator to require a `Signed-off-by:` trailer in
    the block. Add an `invalid-missing-signoff.md` fixture to
    `.github/workflows/tests/pr-lint-fixtures/`. The check fits
    naturally alongside the existing trailer parsing — failing
    closed here is what the bot relies on. Explicitly: this is a
    *hard* fail in `pr-lint.yml`, not a soft warning, because:

    - The bot rejects the merge if the trailer is missing anyway,
      so a soft warning would just defer the failure.
    - The DCO check on commits is independent — it covers PR
      commits, not the body the bot will paste as the squash body.
      Without this validator extension, a contributor with all
      PR commits signed off could still author a body that omits
      the trailer, and the merged squash commit would lack it.

06. Add `.github/workflows/merge-bot.yml`. Triggers:

    - `pull_request: types: [labeled]` — proceed when the new
      label is `automerge`.
    - `check_suite: types: [completed]` — proceed when the suite
      concludes successfully and the PR carries the `automerge`
      label (sticky-retry path).
    - `workflow_dispatch` with `pr_number` input for maintainer
      break-glass.

    Permissions: `pull-requests: write` (only for the issue-comment
    surface; the merge call itself uses the App token), `contents: read`. NO `id-token: write` (not on the release path).

    Steps:

    1. Mint App token via
       `actions/create-github-app-token@v2` SHA-pinned (release-path-
       adjacent; consistent with `release.yml`'s policy). Inputs:
       `app-id: ${{ secrets.MERGE_BOT_APP_ID }}`,
       `private-key: ${{ secrets.MERGE_BOT_PRIVATE_KEY }}`.
    2. Resolve target PR:
       - On `pull_request.labeled`: PR is `${{ github.event.pull_request }}`.
       - On `check_suite.completed`: enumerate `check_suite.pull_requests[*]`,
         filter to those carrying the `automerge` label.
       - On `workflow_dispatch`: `${{ inputs.pr_number }}`.
    3. Skip-conditions (exit cleanly, no comment):
       - Label is not `automerge` (label-trigger only).
       - PR is already merged or closed.
       - PR is not `mergeable` per GitHub's mergeability state
         (handle `unknown` by retrying once after a short sleep —
         GitHub computes mergeability lazily).
    4. Required-check status:
       - List required checks for the head SHA via
         `gh api 'repos/{owner}/{repo}/commits/{sha}/check-runs'`
         (or the GraphQL `statusCheckRollup` to include the
         deprecated commit-status surface).
       - If any required check is `FAILURE`, `TIMED_OUT`, or
         `CANCELLED`: post `Claude: Cannot merge — required check <name> failed.` and exit 1 (sticky label stays — manual
         recovery path is to fix the check and re-run; the
         check_suite retrigger covers most cases). Do NOT remove
         the label automatically.
       - If any is `PENDING`/`QUEUED`/`IN_PROGRESS`: exit 0 with a
         log line; the `check_suite.completed` retrigger handles it.
       - If all green: proceed.
    5. Extract the `==COMMIT_MSG==` block:
       - `gh pr view <pr> --json body --jq .body > /tmp/body.md`.
       - `python3 scripts/extract-commit-msg-block.py /tmp/body.md > /tmp/commit.txt`.
       - On extraction error (missing block, malformed): post
         `Claude: Cannot merge — ==COMMIT_MSG== block extraction failed: <error>.` and exit 1.
    6. DCO sanity check (defence-in-depth — pr-lint should already
       have caught this):
       - `grep -qE '^Signed-off-by: .+ <.+@.+>$' /tmp/commit.txt`
         or equivalent. If missing, post `Claude: Cannot merge — ==COMMIT_MSG== block has no Signed-off-by: trailer.` and
         exit 1.
    7. Idempotency guard: `gh pr view <pr> --json state` — if
       `MERGED`, log "already merged" and exit 0. Cheap re-check
       right before the API call so a parallel trigger doesn't
       double-call.
    8. Call the merge API:
       - `gh api --method PUT 'repos/{owner}/{repo}/pulls/{n}/merge' -f merge_method=squash -f commit_title="${PR_TITLE}" -f commit_message="$(cat /tmp/commit.txt)"`
       - On 405 with `message: "Pull Request is not mergeable"` —
         re-evaluate mergeability and retry once after 5s; if still
         not mergeable, post a comment and exit 1.
       - On 405 with `message: "Pull Request has already been merged"` — log and exit 0 (idempotent).
    9. On success: post `Claude: Merged via bot.`. Exit 0.

07. Update `pr-lint.yml`:

    - Add an `invalid-missing-signoff.md` fixture.
    - The `validator-self-test` job picks it up automatically (the
      job iterates the fixtures directory).
    - No new job needed — the existing `pr-body-commit-msg` job
      calls the same validator that now enforces the trailer.

08. Add `docs/release/merge-bot-setup.md`:

    - Step 1 — register App `agent-auth-merge-bot`. Permissions:
      `pull_requests: write`, `contents: read`, `metadata: read`.
      No webhooks. Install on `aidanns/agent-auth` only.
    - Step 2 — record App ID + private key as repo secrets
      `MERGE_BOT_APP_ID` and `MERGE_BOT_PRIVATE_KEY`.
    - Step 3 — add the App as a bypass actor on the `main` ruleset
      so its merge call satisfies `required_status_checks` admin.
      `gh api` recipe.
    - Step 4 — once the bot has been live for a release cycle,
      flip `squash_merge_commit_message: BLANK` → `PR_TITLE` (or
      `COMMIT_OR_PR_TITLE` — pick `PR_TITLE` for consistency).
      `gh api` recipe.
    - Step 5 — note that work-issues / contributor agents stop
      using `gh pr merge --auto --squash` and apply the
      `automerge` label instead.
    - Rotation procedure for the App private key (parallels the
      semantic-release-agent-auth recipe in CONTRIBUTING.md).

09. Update `docs/release/rollout-pr-template.md` — add a
    "Follow-up — once #291 lands" section linking to the new setup
    doc and noting that the maintainer-paste step is replaced.

10. Update `CONTRIBUTING.md`:

    - In "Writing PRs", replace the
      "Interim mechanics until the merge bot lands" subsection
      with a "Merge mechanics — `automerge` label" subsection
      pointing at the new bot.
    - Cross-reference the setup doc.

11. Update `CLAUDE.md`:

    - Drop the parenthetical "Until the merge bot lands (#291)…"
      from the `==COMMIT_MSG==` convention bullet — the bot is
      now live.
    - Add a one-line note to the `==COMMIT_MSG==` bullet pointing
      at the `automerge` label as the merge trigger.

12. Add `changelog/@unreleased/pr-<N>-merge-bot-commit-msg.yml`
    once the PR number is known. `type: feature`. Description
    explains the maintainer-paste replacement.

## Post-implementation standards review

- **Coding standards (`coding-standards.md`)** — Python extractor
  CLI uses `argparse`, type-annotated functions, descriptive verb
  names. The library function is `extract_block` (verb-noun, like
  `parse_trailer_block`). No raw tuples for structured returns.
- **Service design (`service-design.md`)** — N/A; no service
  surface added. The merge bot is a CI workflow.
- **Release and hygiene (`release-and-hygiene.md`)** — the bot
  produces a squash commit on `main` whose body matches the
  `==COMMIT_MSG==` block exactly; trailers (Signed-off-by, Closes)
  round-trip into git history. Acceptance criterion is verified by
  the first PR merged via the bot (this PR's own merge will use
  the legacy `gh pr merge --auto --squash` path because the bot
  ships in this PR — the next PR will exercise the bot end-to-end).
- **Testing standards (`testing-standards.md`)** — extractor unit
  test covers the public `extract_block` API against the existing
  fixtures (no internal-state poking). The validator self-test
  picks up the new `invalid-missing-signoff.md` fixture
  automatically. The merge bot itself is integration-tested by its
  first end-to-end run on the next merging PR — no in-CI dry-run
  fixture is added because faking a PR merge against a fork repo
  has more setup cost than value (the bot is small and the
  failure mode surfaces as a `Claude: Cannot merge` comment that
  is easy to react to).
- **Tooling and CI (`tooling-and-ci.md`)** — `actions/create-github- app-token@v2` is SHA-pinned (release-path-adjacent — the bot
  authors the squash commit that becomes a release-bumping commit).
  No new dependency on `task` is added; the bot is GitHub-hosted-
  only. The validator's existing `task` integration (none — it's
  PR-only) carries over.

## Acceptance

- The merge bot workflow file exists and lints clean
  (`actionlint`-equivalent — covered by `task lint`'s shellcheck
  on the inline scripts).
- The extractor unit test passes; the validator self-test job
  picks up the new `invalid-missing-signoff.md` fixture and
  reports the expected failure exit.
- `pr-lint.yml` rejects a PR whose `==COMMIT_MSG==` block lacks a
  `Signed-off-by:` trailer.
- `docs/release/merge-bot-setup.md` walks the maintainer through
  App creation, secret naming, and ruleset bypass configuration.
- `docs/release/rollout-pr-template.md` references the new bot.
- `CONTRIBUTING.md` and `CLAUDE.md` describe the `automerge`
  label workflow.
- ADR 0038 records the App-identity / label-trigger / refuse-on-
  lint-fail decisions.
- `changelog/@unreleased/pr-<N>-merge-bot-commit-msg.yml` exists
  with `type: feature`.

The end-to-end behaviour (squash commit body matches the block
exactly; non-conformant PRs cannot be merged; bot's merge call
satisfies the `main` ruleset; resulting commits remain DCO-
conformant) is verified on the **next** PR after this one merges
— the App must be installed and secrets configured by the
maintainer first. The PR description's `## Review notes` calls
that out explicitly so the maintainer doesn't expect this PR to
self-validate.
