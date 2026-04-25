<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0039 — Bot-mediated changelog authoring

## Status

Accepted — 2026-04-25.

Builds on
[ADR 0037](0037-palantir-commit-prefixes-and-commit-msg-block.md) (PR
marker grammar) and the YAML schema introduced in #295.

## Context

ADR 0037 added a fenced `==COMMIT_MSG==` block to the PR template so
contributors author the squash-merge commit body in the PR
description. #295 added a per-PR YAML schema under
`changelog/@unreleased/pr-<N>-<slug>.yml` that downstream release
tooling will consume.

Without further automation, the contributor still has to hand-author
the YAML alongside their code change. This is friction:

- The YAML's `type:` field has to be derived from the PR-title prefix
  (`feature:` -> `type: feature`, `fix:` -> `type: fix`, ...). The
  contributor has to look up the table in CONTRIBUTING.md or guess.
- The YAML's filename has to embed the PR number, which the
  contributor often doesn't know until after `gh pr create`.
- For PRs that legitimately need no changelog (typo fixes, internal
  refactors), the only opt-out today is to hand-apply the
  `no changelog` label. That's an extra GitHub-UI step that breaks
  the PR-text-driven authoring flow.

Phase 3 of #289 calls for a bot to absorb the boilerplate. The
contributor adds one of two markers to the PR description, and the
bot does the rest. The questions this ADR settles:

1. **One bot or two?** The merge bot in #291 also reads the PR
   template (it pastes the `==COMMIT_MSG==` block into the
   squash-merge dialog). Could one App back both?
2. **How does the bot reconcile with manual edits?** A maintainer
   may hand-tune the YAML the bot wrote — or the contributor may
   hand-author the YAML in the first place. The bot must not stomp
   those edits on the next push.
3. **How does the bot avoid an infinite-loop on its own commits?**
   `pull_request: synchronize` fires when the bot pushes its YAML;
   without a guard, the bot would re-trigger itself.

## Considered alternatives

### Single shared GitHub App for both bots

Rejected because:

- The merge bot (#291) needs `pull_requests: write` for the merge
  API but **not** `contents: write` (it never writes files). The
  changelog bot needs `contents: write` on PR branches to commit
  YAMLs but **not** the merge API. Combining them would require the
  merged App to hold both permission sets, widening the blast
  radius of a private-key compromise.
- Each bot's identity tags its commits / labels / comments. Two
  bots on two distinct App identities make the
  `actor.login` / `commit.author` filters in audit history
  unambiguous; one shared identity would force the lockout
  detection (below) to inspect commit messages or other heuristics
  to decide whether a given commit was "this bot's automated
  output" vs. "the same App's other automated output".

### Marker file (`.bot-no-touch`) for opt-out instead of author-history lockout

Rejected because:

- A marker file expands the schema surface (the lint has to know
  about a new file pattern) and adds another file the contributor
  has to remember to commit.
- `git log --format=%an -- <path>` is already the source of truth
  for "did a human touch this file"; a marker file would
  duplicate that signal.

### Re-author on every push (no lockout)

Rejected because:

- A maintainer who hand-edits the YAML to add nuance, fix a typo,
  or tweak the description would have their changes silently
  overwritten on the next push. The fix is then to either fight
  the bot or remove the marker; both are bad ergonomics.
- The lockout is cheap to detect (one `git log` call per
  invocation) and is exactly the desired semantics: "the bot
  bootstraps the file; humans take ownership when they edit it."

### Use the GitHub Actions GITHUB_TOKEN instead of a dedicated App

Rejected because:

- `GITHUB_TOKEN` permissions are scoped per-workflow and cannot
  push to a PR branch in a way that re-triggers downstream
  workflows. The branch-protection ruleset would also need bypass
  rules for the GitHub Actions actor, which is too permissive.
- A dedicated App also lets future bots (e.g. #291's merge bot)
  share the App-token pattern (`actions/create-github-app-token`)
  without re-architecting auth.

## Decision

1. **Dedicated GitHub App** named `agent-auth-changelog-bot`,
   separate from the merge-bot App (#291) and from the
   `semantic-release-agent-auth` App. Permissions:
   `contents: write`, `pull_requests: write`, `metadata: read`.
   Setup steps live in
   [`docs/release/changelog-bot-setup.md`](../../docs/release/changelog-bot-setup.md).

2. **Decision tree** (matches the issue body verbatim, encoded in
   [`scripts/changelog/bot.py`](../../scripts/changelog/bot.py)
   `decide_and_act`):

   1. `==NO_CHANGELOG==` present -> add the `no changelog` label
      (idempotent), skip writing a YAML.
   2. `==NO_CHANGELOG==` absent and the label IS present AND was
      last applied by the bot's identity (per
      `repos/.../issues/<N>/events`) -> remove the label. A
      human-applied label is left in place.
   3. `changelog/@unreleased/pr-<N>-*.yml` already on the PR branch
      -> skip (manual or CLI-authored entry takes precedence).
   4. `==CHANGELOG_MSG==` absent -> skip (lint will fail; that's
      the intentional fall-through path for contributors who
      forgot a marker).
   5. `==CHANGELOG_MSG==` present -> map the PR-title prefix to a
      YAML `type:` per ADR 0037's table, compose the YAML, commit,
      push.

3. **Lockout via author history**. Before composing, run
   `git log --format='%an' -- <candidate-path>` on the PR branch.
   If any author is not the bot identity, skip and exit. An empty
   `git log` (file never committed) is **not** a lockout — the
   file's first commit is the bot's first run.

4. **Loop prevention** via two guards: a workflow-level `if:`
   condition that compares `github.event.pull_request.user.login`
   against the bot login (catches the case where the bot opens a
   PR), and a step-level check that compares the head commit's
   `%an` to the bot's name (catches the
   `pull_request: synchronize` retrigger from the bot's own push).

5. **Idempotency** via two layers: the existing-file check in
   arm 3 short-circuits when a YAML for this PR already exists,
   and a content-equality check in arm 5 skips the commit when the
   file already has the bytes the bot would write. Re-running
   `bot.py --pr N` on the same PR with no body change produces no
   new commits.

6. **`chore:` PRs without an opt-out marker** get a single PR
   comment from the bot explaining that they need
   `==NO_CHANGELOG==` or the `no changelog` label. The comment
   body is fixed (so duplicate-detection doesn't post twice on a
   re-trigger). Once the contributor adds the marker, arm 1 fires
   and the comment becomes a no-op.

7. **`==CHANGELOG_MSG==` and `==NO_CHANGELOG==` markers inside
   HTML comments or fenced code blocks are inert.** The bot
   strips both regions before scanning for markers. This lets the
   PR template ship the markers as commented-out examples and
   lets CONTRIBUTING.md document the markers without triggering
   the bot when an author copies the doc into a PR body.

## Consequences

- The contributor's authoring loop drops from "edit code, hand-
  author YAML, push" to "edit code, write a one-line marker, push".
  The bot composes the YAML on the next push.
- A maintainer who edits the bot-authored YAML claims authorship of
  the file: subsequent bot pushes leave it alone. The reverse
  (revoking the lockout) requires `git rebase`/`git revert`-ing the
  human commit — an explicit operation, which we want.
- The bot adds a new App identity to the project's auth surface.
  Setup steps and key-rotation procedure are in
  [`docs/release/changelog-bot-setup.md`](../../docs/release/changelog-bot-setup.md).
  Compromise of the bot's private key would let an attacker
  commit arbitrary `.yml` files to PR branches, but **not** to
  `main` (PR-branch commits go through the same merge gate as any
  other PR). Blast radius is "noise on PR branches", not
  "production release".
- Contributors who hand-author a YAML continue to work — arm 3
  short-circuits the bot. The marker family is purely additive
  ergonomics; nothing is required.
- A future per-package release train (#275) will need the bot to
  emit `packages:` fields. For now the bot only emits workspace-
  wide entries (no `packages:`); that's the conservative default
  and matches the existing schema's "absent means workspace-wide"
  semantics.

## Follow-ups

- #291 — merge bot (separate App) handles the
  `==COMMIT_MSG==` paste-into-merge-dialog step.
- #275 — per-package release trains: extend the bot to emit
  `packages:` fields when the contributor adds a per-package
  marker variant.
- A future ADR if the project adopts a friendlier slug strategy
  (random words from a wordlist) over the current short hash. The
  hash is sufficient for uniqueness and idempotency; the user-
  facing slug only appears in the filename.
