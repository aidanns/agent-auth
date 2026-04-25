<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan 0003 — Bot-mediated changelog authoring (#298)

Sub-issue of #289. Phase 3 ergonomics on top of #290's marker grammar
and #295's YAML schema/lint. A dedicated GitHub App reads two new
optional PR-description markers (`==CHANGELOG_MSG==`,
`==NO_CHANGELOG==`) and either commits a changelog YAML to the PR
branch or applies the `no changelog` label, so contributors do not have
to hand-edit `changelog/@unreleased/*.yml`.

## Scope

- `.github/workflows/changelog-bot.yml` — Action triggered on
  `pull_request: { types: [opened, edited, synchronize, unlabeled] }`.
  Mints an installation token from the
  `agent-auth-changelog-bot` App via
  `actions/create-github-app-token@v2` (using new
  `CHANGELOG_BOT_APP_ID` + `CHANGELOG_BOT_PRIVATE_KEY` secrets), checks
  out the PR head, and runs the Python entrypoint below.
- `scripts/changelog/bot.py` — type-annotated CLI implementing the
  decision tree from the issue body. Public surface:
  `python scripts/changelog/bot.py --pr <N>`. Reuses
  `extract_block` from `scripts/validate-commit-msg-block.py` (refactored
  to take a generic block name) for `==CHANGELOG_MSG==` /
  `==NO_CHANGELOG==` extraction. Honours the lockout: any commit
  touching the candidate file authored by an identity other than the
  bot disables further bot edits for the lifetime of the PR.
- `scripts/validate-commit-msg-block.py` — minimal refactor: extract
  the `extract_block(body, name)` function and re-use it from the
  `==COMMIT_MSG==` validator. Existing validator-self-test fixtures
  must continue to pass.
- `.github/PULL_REQUEST_TEMPLATE.md` — replace the inert `#298 reserved`
  comment with active, opt-in markers (commented out by default; the
  PR-template comment explains how to use them).
- `CONTRIBUTING.md` — extend "Changelog entries" with the marker family,
  the `==CHANGELOG_MSG==` happy path, the `==NO_CHANGELOG==` opt-out,
  and the lockout behaviour. Cross-reference the new setup doc.
- `docs/release/changelog-bot-setup.md` — maintainer instructions to
  create the `agent-auth-changelog-bot` App, scope it
  (`contents: write`, `pull_requests: write`, `metadata: read`),
  install on `aidanns/agent-auth`, and store the App-ID + private-key
  secrets.
- `design/decisions/0039-bot-mediated-changelog-authoring.md` — ADR
  capturing why a dedicated App (vs. reusing the merge bot's identity),
  the lockout-by-author-history reconciliation strategy, the rewrite-
  on-edit behaviour, and the loop-prevention guard.
- `scripts/changelog/tests/test_bot.py` — unit tests covering prefix
  mapping (every entry in the table), `extract_block` for
  `==CHANGELOG_MSG==`, lockout detection, slug generation, YAML
  composition (output passes `scripts/changelog/lint.py`).
- A bootstrap `changelog/@unreleased/pr-<N>-*.yml` for this PR
  (`type: feature`) — the bot doesn't exist on `main` yet so the
  contributor still has to author the first one.

## Out of scope

- The squash-merge bot that pastes the `==COMMIT_MSG==` block into the
  merge dialog — owned by #291. The two bots are intentionally
  separate Apps (different scopes; each can be deauthorised
  independently).
- Per-package release trains (#275). The bot writes a workspace-wide
  entry (no `packages:` field) when the contributor doesn't specify
  one; tomorrow's per-package surface lands in #275.
- Changing `scripts/changelog/lint.py` schema rules. The bot writes
  YAML that already satisfies the existing lint.
- Decommissioning `.releaserc.mjs` (#296).

## Design and verification

- **Verify implementation against design doc** — N/A. This is a
  contributor-tooling change, not a service. The marker semantics live
  in CONTRIBUTING.md and the ADR.
- **Threat model** — minimal, but worth recording the surface:
  - The bot runs on `pull_request` (not `pull_request_target`) so a
    fork PR cannot mint a write-token from this workflow. The token
    only gets created on PRs from branches in this repo. Any bot
    commit lands on the PR head branch and goes through the same
    branch-protection rules at merge time.
  - The bot reads PR title and body (untrusted user content) and
    interpolates them into a YAML file. We never `eval`/shell-execute
    the content; YAML is composed via `yaml.safe_dump` (or an
    equivalent quoting helper) so a malicious title / body cannot
    break out of the schema.
  - Loop prevention: the workflow skips itself when the head commit is
    authored by `agent-auth-changelog-bot[bot]`. The bot's own commit
    triggering `pull_request: synchronize` would otherwise create a
    fork bomb.
- **Post-incident review (PIR)** — N/A; not a vulnerability fix.
- **Architecture Decision Records** — write
  `design/decisions/0039-bot-mediated-changelog-authoring.md`. The
  novel choices vs. existing convention are: dedicated App separate
  from #291's merge bot, lockout-via-author-history rather than a
  marker file, rewrite-on-edit while not locked out, and the
  bot-actor loop guard.
- **Cybersecurity standard compliance** — `pull_request` not
  `pull_request_target`; least-privilege scopes
  (`contents: write` only on PR branches; `pull_requests: write` for
  label management; `metadata: read`). No id-token; the bot is not on
  the release-publish path. ASVS doesn't apply (CI tooling).
- **Verify QM / SIL compliance** — N/A; SIL is product-side.

## Implementation

### 1. Refactor `scripts/validate-commit-msg-block.py`

Extract:

```python
def extract_block(body: str, marker: str) -> str | None:
    """Return the body between the two `==<marker>==` lines, or None.

    Raises ValidationError if exactly one marker line appears (mismatched).
    """
```

The existing `extract_block(body)` becomes a thin wrapper that hard-codes
`marker="COMMIT_MSG"` and re-raises on `None`. The fixture suite under
`.github/workflows/tests/pr-lint-fixtures/` still passes.

### 2. Add `scripts/changelog/bot.py`

Public CLI:

```text
usage: bot.py --pr N [--repo OWNER/REPO] [--repo-root PATH] [--dry-run]
```

Decision tree (matches the issue body verbatim):

01. Fetch PR title, body, labels, head ref via `gh api`. Cache the
    JSON in a single call to keep rate-limit pressure low.

02. If `==NO_CHANGELOG==` token is present in the body:

    - Ensure `no changelog` label is set (add if missing). Skip writing
      a YAML. Exit 0.

03. Else if `==NO_CHANGELOG==` is absent and the label IS present AND
    was applied by the bot's identity (per
    `gh api repos/.../issues/<N>/events` filtered by
    `event=labeled`, `label.name=no changelog`,
    `actor.login=agent-auth-changelog-bot[bot]`): remove the label.
    A human-applied `no changelog` label is left in place.

04. Else if a file matching `changelog/@unreleased/pr-<N>-*.yml`
    already exists on the PR branch's working tree: skip (manual or
    CLI-authored entry takes precedence). Exit 0.

05. Else if `==CHANGELOG_MSG==` is absent: skip silently. The
    downstream `Changelog Lint` job (#295) will fail the PR; that is
    intentional fall-through.

06. **Lockout check** — for the candidate path
    (`changelog/@unreleased/pr-<N>-<slug>.yml`): run
    `git log --format='%an' -- <path>` on the PR branch. If any line
    is not equal to `agent-auth-changelog-bot[bot]`: skip and exit 0.
    Empty output (no commits yet) is NOT a lockout — only an
    explicitly non-bot author triggers it.

07. Map the PR-title prefix to a YAML `type:` per the table from the
    issue:

    | Prefix         | YAML `type:`                |
    | -------------- | --------------------------- |
    | `feature:`     | `feature`                   |
    | `improvement:` | `improvement`               |
    | `fix:`         | `fix`                       |
    | `break:`       | `break`                     |
    | `deprecation:` | `deprecation`               |
    | `migration:`   | `migration`                 |
    | `chore:`       | (skip + comment, see below) |

    `chore:` PRs without `==NO_CHANGELOG==` get a single PR comment
    explaining the `==NO_CHANGELOG==` / `no changelog` label
    requirement, then exit 0. The comment is idempotent — if the bot
    already posted the same body, we don't post again.

08. Compose the YAML at `changelog/@unreleased/pr-<N>-<slug>.yml`:

    ```yaml
    # SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
    #
    # SPDX-License-Identifier: MIT

    type: <type>
    <type>:
      description: |
        <CHANGELOG_MSG content>
      links:
        - https://github.com/aidanns/agent-auth/pull/<N>
    ```

    `<slug>` is derived deterministically from `(pr_number, content)`
    via a short truncated hash so re-runs on the same content produce
    the same filename (idempotency). Implementation:
    `hashlib.sha1(...).hexdigest()[:8]` — collision risk is irrelevant
    inside a single PR's filename.

09. Write the file, set `git config user.email/name` to the App's
    bot identity (`agent-auth-changelog-bot[bot]` /
    `<numeric-id>+agent-auth-changelog-bot[bot]@users.noreply.github.com`),
    `git add`, `git commit -s -m "chore(changelog): regenerate entry"`,
    and `git push origin HEAD:<head-ref>`.

10. Idempotency: at step 6, before composing, if the file exists AND
    its content is byte-equal to what we'd write, skip the commit. The
    workflow re-fires on every push including the bot's own (loop
    guard at the workflow level catches the loop; this catches the
    same-content case for an untriggered re-run e.g. a label-only
    edit).

### 3. `.github/workflows/changelog-bot.yml`

```yaml
on:
  pull_request:
    types: [opened, edited, synchronize, unlabeled]

permissions:
  contents: read   # workflow file's default; the bot uses an App token
  pull-requests: read

jobs:
  changelog-bot:
    if: github.event.pull_request.user.login != 'agent-auth-changelog-bot[bot]'
    # ... and the head commit author check inside the script.
```

Steps:

1. `actions/create-github-app-token@v2` — mint a token from
   `CHANGELOG_BOT_APP_ID` + `CHANGELOG_BOT_PRIVATE_KEY`.
2. `actions/checkout@v6` against `head.ref` with the App token,
   `fetch-depth: 0` so `git log --format='%an' -- <path>` resolves
   the file's full history.
3. `actions/setup-python@v5` — Python 3.11 only (no `uv sync` needed;
   the script depends on stdlib + PyYAML, which is already in the
   workspace lockfile).
4. Run `python scripts/changelog/bot.py --pr ${{ pr_number }}`.

The job uses `pull_request` (not `pull_request_target`) so fork PRs
do not get the App token. Maintainer-authored PRs from branches on
this repo are the only audience.

### 4. PR template + CONTRIBUTING.md

PR template change: replace the inert `#298 reserved` comment block
with active, commented-out marker placeholders. The contributor
uncomments one. Both markers stay optional — the lint still passes
when the contributor hand-authors a YAML and uses neither marker.

CONTRIBUTING.md change: add a "Bot-mediated authoring" subsection
under "Changelog entries (`changelog/@unreleased/*.yml`)" describing
the three markers, the rewrite-on-edit behaviour, the lockout, and
the `chore:` requirement.

### 5. Setup doc

`docs/release/changelog-bot-setup.md` mirrors
`CONTRIBUTING.md`'s existing semantic-release-app section: numbered
steps to create the App, set permissions, install on the repo, and
store the secrets. Calls out that this App is **separate** from
`semantic-release-agent-auth` (release path) and from #291's merge bot
App (squash-merge dialog).

### 6. ADR 0039

Captures: dedicated-App rationale, lockout-by-author-history strategy,
rewrite-on-edit behaviour, loop-prevention guard. Cross-references
ADR 0037 (marker grammar) and #295's lint.

### 7. Bootstrap changelog entry

`changelog/@unreleased/pr-<N>-changelog-bot.yml` — `type: feature`,
description noting the new bot. Hand-authored (this is the first PR
that ships the bot).

## Post-implementation standards review

- **Coding standards (`coding-standards.md`)** — Python `bot.py` uses
  `argparse`, type-annotated functions, descriptive verb names. No raw
  tuples for structured returns. The PR identity is wrapped in a
  `BotIdentity` named tuple to keep the email/name pair atomic.
- **Service design (`service-design.md`)** — N/A; no service surface.
- **Release and hygiene (`release-and-hygiene.md`)** — bot-authored
  commits carry `Signed-off-by:` (DCO compliance for non-exempt
  identities; the App's bot identity is exempted by GitHub's bot
  detection but `git commit -s` is the universal safe choice).
  Setup doc lives under `docs/release/` alongside the existing
  rollout doc.
- **Testing standards (`testing-standards.md`)** — `bot.py` has unit
  tests under `scripts/changelog/tests/` covering: prefix mapping
  (every Palantir prefix), `extract_block` for `==CHANGELOG_MSG==`,
  lockout detection (mocked `git log` outputs), slug generation,
  YAML composition (output passes `lint.py`). Tests use the public
  module surface, no monkey-patching of internals.
- **Tooling and CI (`tooling-and-ci.md`)** — `actions/create-github- app-token@v2` and `actions/checkout@v6` are pinned by SHA per the
  policy for any workflow that holds `contents: write` (the App
  token does, even though the workflow file's `permissions:` block
  does not). `actions/setup-python@v5` likewise pinned.

## Acceptance

- A PR with `==CHANGELOG_MSG==` and no existing entry produces a
  committed YAML file with type derived from the PR-title prefix.
- A PR with `==NO_CHANGELOG==` gets the label and no file is created.
- Removing `==NO_CHANGELOG==` and pushing again removes the label
  (only when the bot applied it; a human-applied label is preserved).
- A PR with neither marker and no manually-added file falls through
  to #295's lint failing as expected.
- Bot-authored commits carry a `Signed-off-by:` trailer.
- The bot does not modify a PR after a maintainer has hand-edited the
  YAML on the same branch.
- The bot does not infinite-loop on its own commits (workflow `if:`
  guard).
- Idempotency: running `bot.py --pr N` twice on the same PR (no body
  change) produces no new commits.
- All existing `validator-self-test` fixtures continue to pass after
  the `extract_block` refactor.
