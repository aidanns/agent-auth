<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# merge-bot — respond to `@-mention` comment commands

Closes #504. Adds a comment-driven trigger surface to
`.github/workflows/merge-bot.yml` so a contributor (or any user with
`write` permission on the repo) can ask the bot to perform a discrete
operation on a PR by posting `@agent-auth-merge-bot <verb>` in a PR
comment. First verb shipped: `update` — calls the same
`PUT /pulls/{n}/update-branch` path the BEHIND auto-update step uses
inside the `merge` job, but in isolation, without a merge attempt.

## Context

Today the only way to nudge `agent-auth-merge-bot` is to apply or
remove the `automerge` label. There is no way to ask it to perform a
discrete operation on a PR — most concretely, to update a PR's branch
against `main` *without* also asking it to merge.

The bot already knows how to do an `update-branch`: the
`Detect BEHIND and auto-update branch` step inside the `merge` job
calls `PUT /pulls/{n}/update-branch` with `expected_head_sha` pinned
when a labeled PR is `BEHIND`. But that path only runs as part of a
merge attempt. A contributor who wants to verify CI on top of the
latest `main` *before* committing to a merge has no way to trigger it.

Comment-command dispatch is also a stepping-stone toward #428 (move
the bot off Actions to a hosted webhook service): the verb-dispatch
shape, authorization model, and reaction protocol designed here all
port to the hosted handler unchanged. Only the trigger plumbing
(`on: issue_comment` → HTTP webhook) changes.

## Proposal

A new top-level `command` job in `merge-bot.yml`, sibling to the
existing `merge`, `label-needs-fix`, and `sweep` jobs. Triggered by
`on: issue_comment: types: [created]`. The job filters non-PR
comments and non-prefixed bodies cheaply in the `if:` predicate,
authorizes the commenter via `GET /repos/.../collaborators/{user}/permission`,
posts a 👀 reaction to acknowledge, dispatches on the verb via a
small `case`-statement table (today: `update` only), and posts a 👍
or 👎 reaction depending on the outcome. A follow-up PR comment is
posted *only* on structured failures (e.g. `update-branch` API
errors) — mirroring the `Claude: Cannot ...` style the legacy bot
used before #503 stripped its merge-time PR-comment surface.

### Trigger and `if:` predicate

Add to `on:`:

```yaml
issue_comment:
  types: [created]
```

Cheap pre-filter on the new `command` job's `if:` so we don't burn a
runner on every issue or PR comment:

```yaml
if: |
  github.event_name == 'issue_comment'
  && github.event.action == 'created'
  && github.event.issue.pull_request != null
  && startsWith(github.event.comment.body, '@agent-auth-merge-bot ')
  && github.event.comment.user.type != 'Bot'
```

- `event.issue.pull_request != null` rejects issue (non-PR) comments.
- `startsWith(...)` rejects unrelated PR comments without an API call.
- `event.comment.user.type != 'Bot'` is the self-mention guard. The
  App posts as `Bot`-type users, so a future command-output comment
  that happens to mention the bot cannot loop. Independent of name
  comparison so a rename of the App slug doesn't break it. (Belt-and-
  braces: the verb dispatch step also checks the actor login is not
  the bot's own login.)

### Verb dispatch table

A single `case` on the parsed verb:

```bash
case "${VERB}" in
  update)
    # call PUT /pulls/{n}/update-branch — see "update verb" below
    ;;
  *)
    # unknown verb — react 👎, optional comment
    ;;
esac
```

Today the only known verb is `update`. The table shape is
deliberate: follow-up commands (`merge`, `cancel`, `rebase`, …) get a
new `case` arm without revisiting trigger / authorization / reaction
plumbing. Each open-issue follow-up will gate verbs separately
(`merge` requires PR-author approval; `cancel` requires the original
labeller; etc.).

Verb-arg parsing today is just `awk '{print $2}'` on the body's
first line — `@agent-auth-merge-bot update` produces `update`. When
multi-arg verbs land we replace this with a small parser; until
then, anything past the verb is ignored (and noted in the eventual
unknown-verb response).

### `update` verb

Reuses the existing `Detect BEHIND and auto-update branch` step's
shape:

1. `gh pr view <n> --json mergeStateStatus,headRefOid` — re-read
   state right before the API call. Same UNKNOWN polling loop the
   merge job uses (10 × 3s) so we don't fall through with a stale
   state.
2. If `mergeStateStatus != BEHIND` after polling → react 👍 and exit
   ("already up to date with main; no-op"). Idempotent per the
   acceptance criterion. UNKNOWN-after-polling reacts 👎 (state
   never resolved — surface as a structured failure).
3. If BEHIND → call `gh api --method PUT "repos/.../pulls/{n}/update-branch" -f expected_head_sha=<sha>`.
4. Treat `expected_head_sha` 422 as 👍 with a `::notice::` line
   ("contributor pushed during update; their commit is the new
   head"). Same as the merge-job behaviour: the contributor's push
   is a benign race we don't need to retry.
5. Treat any other `update-branch` API error as 👎 + a follow-up
   `Claude: Cannot update — <api error>` PR comment. The merge job
   only logs `::error::` because the failing required check / red
   PR badge already surfaces the problem; the comment-command path
   doesn't have an equivalent surface for "API call failed", so a
   structured failure comment is required for the user to know
   their request was rejected and why.
6. Success → react 👍. No follow-up comment — the new head SHA on
   the PR (and the resulting CI cycle) is the visible signal that
   the update happened.

### Authorization

`GET /repos/{owner}/{repo}/collaborators/{user}/permission` returns a
permission level (`admin` / `maintain` / `write` / `triage` / `read`
/ `none`). Authorize iff the level is one of `admin / maintain / write` — same gating GitHub's own UI uses for write-tier actions.
Anything below reacts 👎 and exits with a `::notice::` line; no
follow-up PR comment (would invite drive-by command spam, since
unauthorized users by definition aren't trusted to make signal-from-
noise judgements about their own attempts).

The lookup uses the App token (already minted by the existing
`secrets-check` + `Mint merge-bot App token` steps the `merge` job
uses; we factor those steps out per "Code organisation" below). The
App's existing `Metadata: Read-only` grant covers the
collaborator-permission endpoint on user-owned repos. No new App
permission needed.

### Reaction lifecycle

GitHub reactions on `issue_comment` use
`POST /repos/.../issues/comments/{id}/reactions` with a `content`
field of `eyes` / `+1` / `-1`. Three calls per command:

1. `eyes` immediately after the authorization check passes (so the
   user sees the bot has accepted the request before the API work
   starts).
2. `+1` (success) OR `-1` (rejection) at the end of the dispatch
   table.

If authorization fails we post 👎 only — no 👀 first. (Distinguishes
"command rejected because you can't run it" from "command attempted
and failed" to anyone reading the timeline.)

The reaction calls themselves are best-effort: a failed reaction
post emits a `::warning::` and the workflow continues. Losing a
reaction is observable noise but doesn't change the underlying
outcome (the `update-branch` either ran or didn't).

### Self-mention guard

Two layers, defence-in-depth:

1. `if:` filter on `event.comment.user.type != 'Bot'` — rejects all
   App-authored comments at the trigger level so no runner starts.
   Catches the most likely loop source.
2. Inside the job, an explicit name guard reads
   `github.event.comment.user.login` and bails if it matches the
   App's bot login (`agent-auth-merge-bot[bot]` — the `[bot]` suffix
   is appended automatically by GitHub for App-authored comments).
   Catches the unlikely case where a future GitHub change makes
   `user.type` carry a different value for our App.

### Code organisation

The existing `merge` and `label-needs-fix` jobs both inline the
`secrets-check` + `Mint merge-bot App token` step pair. The new
`command` job will inline a third copy of the same pair rather than
factoring all three into a composite action — keeping this PR scoped
to the issue-acceptance surface and minimising the
self-modifying-merge-bot-PR risk (per the auto-memory note,
`actions/checkout` ordering in both `merge` AND `label-needs-fix`
needs to be exact for the merge-bot run that lands this PR not to
crater on a missing composite action). A future cleanup PR can
factor the three call-sites once the third one has merged on `main`
and the duplication is observable; tracked as #584.

The new `command` job DOES need its own `actions/checkout@... with: ref: main` before any `uses: ./.github/actions/...` call —
unlikely to hit one in this PR (the `update` verb is pure
`gh api`-on-shell, no composite action dependency), but adding the
checkout up front leaves the door open for future verbs that wrap
the existing `read-required-contexts` action (e.g. a `recheck` verb
that re-evaluates required-check status).

### Permissions

Workflow-level `permissions:` already grants
`pull-requests: write` (covers reacting on issue-comments — the
endpoint accepts the App-installation `Issues: Read & write` /
`Pull requests: Read & write` grants the App already carries) and
`contents: write` (covers `update-branch`). No change needed.

### Failure surfaces

- Unauthorized commenter → 👎 only, no PR comment.
- Unknown verb → 👎 + PR comment
  `Claude: Unknown verb '<verb>'. Known verbs: update.`
- `update-branch` API error (other than `expected_head_sha`) → 👎
  - PR comment `Claude: Cannot update — <api error>`.
- Reaction post itself failed → `::warning::` only, no PR comment.

### Concurrency

```yaml
concurrency:
  group: merge-bot-command-${{ github.event.comment.id }}
  cancel-in-progress: false
```

Per-comment key so two near-simultaneous comments on different PRs
run in parallel. `cancel-in-progress: false` because cancelling a
mid-`update-branch` call would leave the user without a 👍/👎 — and
the `expected_head_sha` pin on the API call already protects against
the only race that matters (a new push during the update).

## Acceptance

Per the issue:

- Posting `@agent-auth-merge-bot update` on a behind-main PR makes
  the bot react 👀, run `update-branch`, and react 👍 — with no
  merge attempt.
- Posting it from an unauthorized account reacts 👎 and does
  nothing.

Verification path: this is a workflow change, so end-to-end
acceptance can only be tested *after* the workflow lands on `main`.
The new `command` job will not exist on `main` until the squash-
merge lands; the merge-bot run that processes this PR consumes the
on-`main` definition (the `Detect BEHIND and auto-update branch`
step is unchanged), so the PR landing itself doesn't depend on the
new code path being callable.

Post-merge verification (matches the issue's acceptance criterion):

1. **Authorized happy path** — on a behind-main test PR, post
   `@agent-auth-merge-bot update` from an account with `write+`
   permission. Expect:
   - 👀 reaction appears within seconds of posting.
   - Bot calls `update-branch`; the PR head advances to a merge
     commit by `agent-auth-merge-bot[bot]`.
   - 👍 reaction follows.
   - No merge attempt (the PR remains open; no `Merged` activity).
2. **Authorized no-op path** — on an up-to-date PR, post the same
   command. Expect:
   - 👀 → 👍 (idempotent no-op).
   - No new commits on the PR.
3. **Unauthorized path** — from an account with `read` / `none`
   permission (or no account; comment-as-non-collaborator), post
   the same command. Expect:
   - 👎 reaction only (no 👀).
   - No PR comment, no `update-branch` call.

The orchestrator should run probes 1 and 3 once the PR merges; the
result lands on the issue as the "Acceptance verified" comment.

## Plan-template checklist

- **Verify implementation against design doc** — N/A; no design doc
  changes (this is an additive surface on an existing workflow). The
  ADR 0038 update path covers any future move to the hosted
  webhook handler under #428; no new ADR required for this
  command surface (the dispatch table is small, internal, and
  superseded by the #428 design).
- **Threat model** — security-relevant change (new external trigger
  - authorization gate). Threat shape: drive-by spam, privilege
    escalation via crafted comment body, self-loop via App-authored
    comment. All three are addressed by the `if:` filter +
    collaborator-permission gate + self-mention guard documented
    above; no `SECURITY.md` edit required because the merge bot's
    trust boundary doesn't change (App token still mints with the same
    permission set; no new attack surface against `main`).
- **Post-incident review** — N/A; not remediating a vulnerability.
- **ADRs** — N/A per "Verify against design doc" above.
- **Cybersecurity standard compliance** — verb dispatch +
  authorization gate is OWASP ASVS L1 V4.1 (general access control)
  and L1 V13.1 (generic web service security). Both satisfied by the
  permission-level gate (write+).
- **Verify QM / SIL compliance** — N/A; merge-bot is QM (per ADR 0019
  / 0038, automation-only path with a manual rollback via direct
  `gh api` call).
- **Coding standards** — bash steps follow the existing
  `set -euo pipefail` + `env:`-tunneled-input pattern in
  `merge-bot.yml`. No new Python / Rust code.
- **Service design standards** — N/A; workflow change, no service
  surface affected.
- **Release and hygiene standards** — `feature(ci):` PR; hand-author
  changelog entry under `changelog/@unreleased/` per the project
  policy (changelog-bot does not auto-author).
- **Testing standards** — workflow test coverage is via
  `actionlint` + post-merge live-fire on a real PR (see
  Verification path above). No new unit test surface (the
  merge-bot itself has no unit-test harness — every prior change to
  this workflow has been verified the same way).
- **Tooling and CI standards** — workflow filename / `name:` /
  composite-action naming all follow ADR 0046 conventions. New
  composite action sits at `.github/actions/mint-merge-bot-app-token/action.yml`,
  `name: mint-merge-bot-app-token`.

## Out of scope

- Any verb other than `update` — open separate issues per command
  before adding more `case` arms.
- Changing the existing label-driven merge trigger.
- Migration to the hosted webhook handler (#428) — this PR's verb-
  dispatch shape, authorization model, and reaction protocol are
  designed to port over unchanged.
