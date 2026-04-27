<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# merge-bot — close residual automerge event-coverage gaps

Closes #388. Builds on PR #383 / issue #374 (BEHIND-handling) by
adding two trigger surfaces to `.github/workflows/merge-bot.yml` so
state transitions that today produce no merge-bot trigger event
stop wedging `automerge`-labeled PRs indefinitely.

## Context

PR #383 made merge-bot self-heal a BEHIND PR by calling
`PUT /pulls/{n}/update-branch` from inside the existing job — but
only when the bot fires for some other reason. Two adjacent gaps
remain:

1. **PR labeled `automerge`, was up-to-date when the bot last
   fired, then `main` moved.** No `workflow_run.completed` will
   fire on this PR until someone pushes to it; the BEHIND-handling
   step only helps if the bot fires in the first place.
2. **`automerge` set before final approval lands.** The bot fires
   once on `pull_request: labeled`, exits because the review
   requirement is unmet, and never re-fires when the approval
   eventually arrives — there is no `workflow_run.completed` event
   tied to a review submission.

Both are the same shape: an event-driven bot misses a state
transition because the transition does not currently produce one
of its trigger events.

## Proposal

Two new `on:` triggers and one new sweep job:

### `push: branches: [main]` — sweep open `automerge` PRs

Whenever `main` advances, list every open PR carrying the
`automerge` label and re-process each. New `sweep` job, separate
from the existing per-PR `merge` job. Lists PRs with
`gh pr list --label automerge --state open`, then fans out to the
existing `merge` job via `gh workflow run merge-bot.yml -f pr_number=<N>` (one `workflow_dispatch` per PR).

Sweep concurrency: `group: merge-bot-sweep`,
`cancel-in-progress: true` so a burst of merges to `main`
collapses into one sweep. Per-PR concurrency key
(`merge-bot-<n>`) is unchanged, so the dispatch fan-out cannot
stomp on a PR already being processed by a label or workflow_run
trigger.

`branches: [main]` only — explicitly NOT firing on tag pushes
(release tags would otherwise trigger sweeps with nothing to do).

### `pull_request_review: types: [submitted, dismissed]`

Re-fire merge-bot when a review state changes:

- `submitted` covers the "approval lands after CI completed and
  after label was set" case.
- `dismissed` lets a queued-but-now-unapproved PR early-exit
  cleanly (the existing in-job `mergeable` / required-reviews
  checks decide; the bot just no-ops if the PR is no longer
  approved).

PR number resolves directly from `github.event.pull_request.number`
in the existing `Resolve target PR` step's `pull_request` case —
the `pull_request_review` event payload exposes
`event.pull_request.number` with the same shape as `pull_request`.
No new resolution code path needed.

## Design decisions

### Fan-out mechanism: `workflow_dispatch` per-PR (Option A)

Confirmed by reading the existing `merge` job: the resolve-PR
logic is single-sourced in the `Resolve target PR` step which
already accepts a PR number via `inputs.pr_number` for the
`workflow_dispatch` case. Picking `workflow_dispatch` per-PR
fan-out lets the sweep delegate to the existing job verbatim:

- Resolve, metadata fetch, required-check inspection, BEHIND
  handling, DCO trailer check, and merge-API call all stay in
  the single `merge` job.
- The existing `merge-bot-<n>` concurrency key already keys on
  `inputs.pr_number` for the dispatch path; multiple sweep-
  triggered dispatches for the same PR queue cleanly behind any
  in-flight run that beat them to it.

The alternative — `strategy.matrix` over a sweep job — would have
to duplicate the resolve / metadata / gating logic inside the
sweep, and the per-PR concurrency wouldn't compose with the
existing `merge-bot-<n>` group. Rejected.

`gh workflow run` only triggers `workflow_dispatch` if the
workflow file on the *default branch* allows it — which it does
(the existing `workflow_dispatch` input is in place).

### Composite action: NOT extracted

The sweep job does need its own secret-check + App-token mint to
call `gh pr list --label automerge` and `gh workflow run`. That
is one duplication of two short steps (~25 lines), not N
duplications. Extracting a composite action under
`.github/actions/merge-bot-token/` would:

- Hide the step IDs (`secrets-check`, `app-token`) that downstream
  conditionals in the existing `merge` job reference, so the
  composite would have to re-export both as outputs and the
  existing job would need to be rewritten to use them.
- Save ~25 lines once.

The cost / benefit doesn't justify the indirection. Inline the
secret-check + token-mint into the sweep job, with a comment
calling out the duplication and pointing at the existing `merge`
job's pair.

### `pull_request_review` job's `if:` predicate

- Fires on both `submitted` and `dismissed` (the trigger types
  declared in `on:`).
- Gates on the PR carrying the `automerge` label using the event
  payload's `github.event.pull_request.labels.*.name` — this is
  reliable on `pull_request_review` events and avoids burning a
  runner per review on non-automerge PRs.
- Does NOT gate on `review.state == 'approved'` — that would
  duplicate GitHub's required-reviews logic in the workflow
  predicate. The existing in-job gating (which calls
  `gh pr view --json mergeable,mergeStateStatus` and the merge
  API) is the source of truth; let it decide.

### Sweep job's `if:` predicate

Gated on `github.event_name == 'push' && github.ref == 'refs/heads/main'`. Tag pushes go to `refs/tags/...` and so
naturally fall outside the predicate.

### CodeQL `js/actions/command-injection` discipline

Every new `run:` block consuming event-payload values binds the
value through `env:` and quotes `${VAR}` rather than templating
`${{ ... }}` directly into shell. The existing file already uses
this pattern; new code must too. Specifically:

- Sweep job: `gh pr list` output (PR numbers) are integers from
  GitHub's API and not author-controlled, so they don't need the
  same level of defence — but bind them through `env:` anyway
  for consistency with the surrounding pattern.
- `pull_request_review` payload values flow into `Resolve target PR` only via the existing `PULL_REQUEST_NUMBER` env binding,
  which is already in place.

### Header doc-comment block

Update the trigger-surface comment block at the top of the file
to include both new triggers and a one-paragraph rationale for
each. Don't let the doc drift from the workflow.

## Test plan

Static checks (no end-to-end smoke required for the `push:main`
path):

- [ ] `yq .github/workflows/merge-bot.yml > /dev/null` parses
  cleanly.
- [ ] The `on:` block contains `push: branches: [main]` and
  `pull_request_review: types: [submitted, dismissed]`.
- [ ] The new sweep job's `if:` is gated on
  `github.event_name == 'push' && github.ref ==     'refs/heads/main'`.
- [ ] The existing `merge` job's `if:` chain accepts the new
  `pull_request_review` event only when the PR carries the
  `automerge` label
  (`contains(github.event.pull_request.labels.*.name,     'automerge')`). The existing `Skip if PR is not in scope`
  step still early-exits as a defence-in-depth.
- [ ] The existing `concurrency.group` expression resolves
  correctly for `pull_request_review` (uses
  `github.event.pull_request.number`) and for the new sweep
  job (uses the literal `merge-bot-sweep` group).
- [ ] Every new `run:` block binds event-payload values through
  `env:` (CodeQL discipline).
- [ ] Every new `uses:` reference (composite action calls,
  checkout, etc.) is SHA-pinned per
  `.claude/instructions/tooling-and-ci.md`.
- [ ] The header trigger-surface comment block lists the two new
  triggers with a one-paragraph rationale each.
- [ ] `changelog/@unreleased/pr-<N>-merge-bot-event-gaps.yml`
  exists with `type: improvement` and links to issue #388 and
  this PR.
- [ ] `git log -p -1 .github/workflows/merge-bot.yml` shows no
  drift from `main` outside the documented changes.

Live smoke (only the `pull_request_review` path can be tested on
this PR itself):

- [ ] Submit a review on this PR after CI is green and confirm
  merge-bot fires (visible in the PR's checks rollup as a new
  `Merge Bot` run keyed to the `pull_request_review` event).
- [ ] The `push:main` sweep is verifiable post-merge: after this
  PR merges, observe one sweep run firing on the merge
  commit's push to `main`. No `automerge` PRs are likely to
  be open at that moment, so the sweep will exit cleanly with
  "no PRs to dispatch" — that's the expected steady state.

## Design and verification

- **Verify implementation against design doc** —
  `design/decisions/0038-merge-bot-via-github-app.md` describes
  the App-mediated merge mechanism but does not enumerate the
  trigger surface; this change adds two triggers to the existing
  workflow without altering the App-token / merge-API flow. No
  ADR amendment needed; the workflow header comment block carries
  the rationale.
- **Threat model** — no new trust boundaries introduced. The new
  triggers (`push`, `pull_request_review`) run under the
  workflow-default `GITHUB_TOKEN` for trigger delivery; the App
  token mint is unchanged. `pull_request_review` runs against the
  PR head, but the bot does no checkout of contributor code (it
  only reads PR metadata via `gh api`); no new attack surface.
- **PIR** — N/A (not remediating a confirmed vulnerability).
- **ADR** — not needed (incremental hardening of an existing
  component documented in 0038).
- **Cybersecurity standard compliance** — N/A
  (workflow change, no application-layer surface).
- **QM / SIL compliance** — N/A.

## Post-implementation standards review

- **`coding-standards.md`** — N/A (YAML workflow; no code).
- **`service-design.md`** — N/A.
- **`release-and-hygiene.md`** — hand-authored changelog YAML
  required (improvement-tier); apply the `automerge` label after
  CI green; do not push a commit that bypasses DCO sign-off.
- **`testing-standards.md`** — N/A (no test code changes).
- **`tooling-and-ci.md`** — every new `uses:` SHA-pinned;
  release-path-adjacent so the policy applies in full.
