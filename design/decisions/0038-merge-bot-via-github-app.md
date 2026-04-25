<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0038 — Merge bot via dedicated GitHub App + `automerge` label

## Status

Accepted — 2026-04-25.

## Context

ADR 0037 (#290) introduced the `==COMMIT_MSG==` block in the PR
template. The interim mechanic until this issue (#291) lands is that
the maintainer copy-pastes the block into the squash-merge dialog by
hand, gated by `squash_merge_commit_message: BLANK` so the dialog
defaults to an empty body. That manual step is the failure mode this
ADR removes.

The bot has to:

1. Determine when the PR is ready to merge (review approved, every
   required check green).
2. Read the PR body and extract the `==COMMIT_MSG==` block.
3. Call `PUT /repos/.../pulls/{n}/merge` with `merge_method: squash`,
   `commit_title: <PR title>`, `commit_message: <extracted block>`.
4. Refuse to merge if the body fails the `pr-lint` validator or
   any required check failed.
5. Have a credential GitHub accepts as satisfying the `main` ruleset's
   `required_status_checks` administration so the merge call doesn't
   bounce off branch protection.

Three orthogonal questions fall out of that:

- **What credential mints the merge call?**
- **What triggers the bot?**
- **What does it do when the lint or checks fail?**

## Considered alternatives

### Credential: default `GITHUB_TOKEN`

**Rejected** because:

- The default token cannot bypass the `main` ruleset's required-
  checks administration, so the merge call gets `405` even when every
  check is green. A bypass-actor entry on the ruleset is the way out,
  and bypass-actor entries are scoped to identities (App
  installations, teams, users) — `GITHUB_TOKEN` is the workflow's
  ephemeral identity and cannot be added.
- Tags and commits authored by `GITHUB_TOKEN` do not fire downstream
  workflow triggers, which would silently break the chain into
  `release.yml` once the squash commit lands on `main`. This is the
  same constraint that drove the semantic-release-agent-auth App
  decision in ADR 0026.

### Credential: reuse the existing `semantic-release-agent-auth` App

**Rejected** because:

- That App holds `contents: write` to push the `chore(release):` commit
  and create tags. The merge bot needs only `pull_requests: write` and
  `contents: read`. Reusing the broader-scoped App for the narrower
  task widens the blast radius of a credential leak. Two Apps with
  least-privilege scopes are easier to revoke independently.
- The two App identities are visible in the commit/audit trail.
  Conflating them obscures *which* automation took which action — a
  release-cut commit and a PR merge should be distinguishable on
  inspection.

### Credential: long-lived PAT

**Rejected** because:

- A PAT is bound to a human account, expires on a human-rotation
  cadence, and surfaces a personal credential to repo Actions. The
  App alternative scopes to a single repo, mints short-lived tokens
  per workflow run, and rotates without touching the human account.

### Trigger: auto-merge as soon as PR is mergeable

**Rejected** because:

- "Mergeable" includes draft PRs and PRs whose required reviews
  haven't completed. The bot would need to re-implement the review-
  gating logic GitHub already provides.
- A purely-automatic trigger has no contributor-visible "ready to
  merge" signal — reviewers can't tell whether they should still be
  looking at the PR. A label is a clear handoff.

### Trigger: `gh pr merge --auto --squash` (the legacy work-issues path)

**Rejected** because:

- `--auto` waits for required checks but uses GitHub's *native*
  squash-merge body, which would re-introduce the noise the
  `==COMMIT_MSG==` convention exists to suppress. The whole point of
  this issue is to take over the body composition.
- A label trigger plus an explicit bot keeps the bot's pre-merge
  decision (lint pass, required-checks status, body extraction)
  observable and overridable. The work-issues agents can apply the
  label exactly the same way they currently call `gh pr merge --auto`.

### Lint-fail behaviour: fall back to BLANK / native squash body

**Rejected** because:

- Falling back hides the failure: the maintainer wouldn't know the
  PR's `==COMMIT_MSG==` block was malformed until they later inspect
  `git log` and find a noisy concatenation. Refuse-on-fail surfaces
  the problem at merge time when the PR author can fix it.
- The lint already runs PR-time and is a required check; an
  inconsistency between "lint passed" and "bot merged with native
  body" would be confusing.

## Decision

1. **Dedicated GitHub App `agent-auth-merge-bot`**, separate from
   `semantic-release-agent-auth`. Permissions: `pull_requests: write`,
   `contents: read`, `metadata: read`. Installed on
   `aidanns/agent-auth` only. Configured as a bypass actor on the
   `main` ruleset so its `PUT /pulls/{n}/merge` call satisfies the
   `required_status_checks` administration.

   - App ID + private key live in repo secrets `MERGE_BOT_APP_ID` and
     `MERGE_BOT_PRIVATE_KEY`.
   - Token is minted in-workflow via `actions/create-github-app-token`
     and is short-lived.

2. **Label trigger.** The workflow listens on
   `pull_request: labeled` (proceed when the label is `automerge`)
   and `check_suite: completed` (proceed when the suite concludes
   green and the PR carries `automerge`). Maintainers and automerge-
   eligible CI agents apply the label once review is satisfied. The
   label already exists in the repo; this subsumes the
   `gh pr merge --auto --squash` flow that the work-issues agents
   currently use.

3. **Refuse on lint or check failure.** If extraction of the
   `==COMMIT_MSG==` block fails, or any required check is `FAILURE`
   / `TIMED_OUT` / `CANCELLED`, the bot posts a `Claude: Cannot merge — <reason>` comment and exits non-zero. It does **not**
   remove the `automerge` label — leaving it sticky lets the
   `check_suite.completed` retrigger pick up a fixed run automatically.
   Pending checks cause a clean exit with a log line; the same
   retrigger handles the green-completion case.

4. **DCO trailer is a hard validator failure.** The bot authors no
   commits — the squash commit's `Signed-off-by:` trailer must
   already be present in the extracted body. The validator
   (`scripts/validate-commit-msg-block.py`) is extended to require
   the trailer, so a contributor learns of the omission at
   PR-author time, not at merge time. The merge bot still spot-
   checks the trailer immediately before calling the API as
   defence-in-depth.

5. **No automatic squash button removal.** Disabling the native
   squash button is a maintainer-side configuration change that
   should follow a release cycle of bot-mediated merges (so the
   maintainer can observe the bot's behaviour before removing the
   fallback). This ADR documents the option in the setup doc but
   doesn't apply it in code.

## Consequences

- The merge mechanic moves from "maintainer pastes the block" to
  "agent applies the label, bot merges". `CONTRIBUTING.md` and
  `CLAUDE.md` are updated to reflect the new flow. The
  `docs/release/rollout-pr-template.md` interim section gets a
  follow-up linking the new setup doc.
- The maintainer must perform a one-time setup before the bot can
  function: register the App, install it on the repo, store the
  secrets, and add the App as a bypass actor on the `main`
  ruleset. `docs/release/merge-bot-setup.md` walks through every
  step.
- The bot does not run against itself: this PR (the one introducing
  the bot) merges via the legacy `gh pr merge --auto --squash`
  path because the bot doesn't exist on `main` yet. The first PR
  merged after this one exercises the bot end-to-end and is the
  effective acceptance test.
- The `pr-lint.yml` validator now requires a `Signed-off-by:`
  trailer in the `==COMMIT_MSG==` block, in addition to the DCO
  workflow's existing per-commit check. Existing PRs with the
  trailer in their commits but missing from the block need an
  edit before they can merge via the bot. (No such PRs are
  currently in flight; the cutover is clean.)
- `squash_merge_commit_message: BLANK` stays in effect until the
  maintainer flips it back (suggested target: `PR_TITLE`). The
  setup doc includes the `gh api` recipe.
- The bot's permissions are deliberately minimal: even a
  full-token-leak scenario gives the attacker only the ability to
  merge PRs, not to push commits or create releases. The
  `semantic-release-agent-auth` App keeps its broader scope; both
  sets of secrets rotate independently.

## Follow-ups

- After a release cycle of bot-mediated merges, disable the native
  squash-merge button at the repo level so the bot is the only
  merge path. Tracked in the maintainer's setup doc; no GitHub
  issue yet (will open if rollback is observed).
- #295 — bot-mediated `version_logic` consumes the squash commit
  body the merge bot produces. The two bots compose: this one
  makes the body deterministic; #295 reads it for release impact.
- #296 — decommissions `.releaserc.mjs`; depends on the body
  shape this bot guarantees.
- #298 — `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` markers; the
  merge bot will need to validate these too once they're active.
- #215 — confirmed obviated by #289's design; no bot-pushed
  release commit means no separate signing-bypass needed for the
  release path. Leave open for #296 to formally close.
