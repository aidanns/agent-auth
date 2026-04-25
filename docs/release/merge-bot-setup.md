<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Merge bot — maintainer setup

One-time maintainer steps to bring the merge bot online. The bot is
the workflow at [`.github/workflows/merge-bot.yml`](../../.github/workflows/merge-bot.yml).
Background and rationale are in
[ADR 0038](../../design/decisions/0038-merge-bot-via-github-app.md).

The bot will not function until **all four steps** below are
completed: App registered, secrets stored, ruleset bypass added,
contributors switch to the `automerge` label.

## What the bot does

When the `automerge` label is applied to a PR (or a `check_suite`
completes successfully on a PR that already carries the label), the
workflow:

1. Fetches the PR body, extracts the contents between
   `==COMMIT_MSG==` markers via
   [`scripts/extract-commit-msg-block.py`](../../scripts/extract-commit-msg-block.py).
2. Verifies every required check is green and the block carries a
   `Signed-off-by:` trailer.
3. Calls `PUT /repos/aidanns/agent-auth/pulls/{n}/merge` with
   `merge_method: squash`, `commit_title: <PR title>`,
   `commit_message: <extracted block>`.
4. Comments `Claude: Merged via bot.` on success, or
   `Claude: Cannot merge — <reason>` on any pre-merge failure
   (label stays applied so the next green run retriggers the
   merge).

The bot authors no commits — it only calls the merge endpoint. This
is why the squash commit body's `Signed-off-by:` trailer must
already sit inside the contributor's `==COMMIT_MSG==` block, and why
[`pr-lint.yml`](../../.github/workflows/pr-lint.yml) enforces the
trailer at PR-author time.

## Step 1 — Register the `agent-auth-merge-bot` GitHub App

1. Go to [github.com/settings/apps/new](https://github.com/settings/apps/new)
   (user-owned App) and create an App with:
   - **App name**: `agent-auth-merge-bot` (any identifier works; the
     name appears as the merge actor in the PR timeline).
   - **Homepage URL**: `https://github.com/aidanns/agent-auth`.
   - **Webhook**: uncheck *Active* — this App does not handle
     events.
   - **Repository permissions**:
     - *Contents*: **Read-only** (needed to inspect the head SHA
       referenced by the merge call).
     - *Metadata*: **Read-only** (mandatory when any other repo
       permission is granted).
     - *Pull requests*: **Read & write** (call `PUT /pulls/{n}/merge`,
       post comments, read body and labels).
     - *Checks*: **Read-only** (inspect required-check status via
       the `statusCheckRollup` GraphQL field).
     - All other permissions: **No access**.
   - **Where can this GitHub App be installed?**: *Only on this
     account*.
2. Click **Create GitHub App**.
3. On the App's settings page:
   - Copy the **App ID** (numeric, shown at the top) for step 2.
   - Under **Private keys → Generate a private key**, download
     the `.pem` file. GitHub shows it once.
4. Open **Install App** and install it against `aidanns/agent-auth`
   only — not *All repositories*.

## Step 2 — Store the App credentials as repo secrets

In the repo's
[Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions),
add:

- `MERGE_BOT_APP_ID` — the numeric App ID from step 1.3.
- `MERGE_BOT_PRIVATE_KEY` — the **full contents** of the `.pem`
  file, including the `-----BEGIN/END` markers and the trailing
  newline.

These names are referenced in the workflow at
[`.github/workflows/merge-bot.yml`](../../.github/workflows/merge-bot.yml)
(`secrets.MERGE_BOT_APP_ID` / `secrets.MERGE_BOT_PRIVATE_KEY`); do
not rename without updating the workflow.

To rotate the private key, generate a new key on the App's settings
page, update `MERGE_BOT_PRIVATE_KEY` in repo secrets, and revoke the
old key from the App settings. No workflow change is required. The
App's tokens are short-lived (≤ 1 hour) so the old key stops being
useful as soon as the next workflow run mints a fresh token.

## Step 3 — Add the App as a bypass actor on the `main` ruleset

The `main` branch ruleset enforces required status checks. The
default `GITHUB_TOKEN` cannot bypass `required_status_checks`
administration; a GitHub App installation can. Add the
`agent-auth-merge-bot` App installation to the ruleset's bypass-actor
list:

Via the UI:

1. Open
   [Settings → Rules → Rulesets](https://github.com/aidanns/agent-auth/settings/rules)
   → `main`.
2. Under **Bypass list → Add bypass → Apps**, search for and select
   `agent-auth-merge-bot`.
3. Set the bypass mode to **Always** (the bot's own pre-merge gating
   replaces the ruleset's; weakening the bot's gating is reviewed
   in PR, not at merge time).
4. **Save changes**.

Via the API (replace `<RULESET_ID>` after listing the rulesets):

```bash
# Find the ruleset ID
gh api 'repos/aidanns/agent-auth/rulesets' --jq '.[] | select(.name == "main") | .id'

# Look up the App's *installation* ID for this repo
gh api 'repos/aidanns/agent-auth/installation' --jq '.id'

# Add the bypass actor (always-on bypass: bypass_mode: "always")
# Patch the existing bypass_actors list — read it first, append,
# and write back so other entries (e.g. the semantic-release App)
# stay in place.
gh api -X PATCH 'repos/aidanns/agent-auth/rulesets/<RULESET_ID>' \
  --input - <<'EOF'
{
  "bypass_actors": [
    {
      "actor_id": <APP_INSTALLATION_ID>,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
EOF
```

Confirm:

```bash
gh api 'repos/aidanns/agent-auth/rulesets/<RULESET_ID>' \
  --jq '.bypass_actors'
```

The merge call will return `405 Pull Request is not mergeable` until
this bypass is in place. That is the failure mode the App identity
solves; verify the bypass is configured before expecting any PR to
land via the bot.

## Step 4 — Switch contributors to the `automerge` label

The `automerge` label already exists on the repo (created during
#290's rollout). Once the bot is live:

- Maintainer-mediated merges: apply the `automerge` label to any
  PR ready to merge. The bot picks it up on the `pull_request: labeled` event. If checks are still pending when you apply the
  label, the bot waits and retriggers on `check_suite: completed`.
- Work-issues / CI agents: replace `gh pr merge --auto --squash`
  in the agent's pipeline with `gh pr edit <pr> --add-label automerge`. The label is the new "ready to merge" signal.
- Any merge attempt that hits a problem (`==COMMIT_MSG==`
  malformed, required check failed, DCO trailer missing) surfaces
  as a `Claude: Cannot merge — <reason>` comment. The label stays
  applied so a fix-and-push retriggers the bot via
  `check_suite: completed`.

## Optional: flip `squash_merge_commit_message` away from `BLANK`

While the maintainer was pasting the `==COMMIT_MSG==` block by
hand, the squash-merge dialog's default body was set to `BLANK` so
the dialog wouldn't pre-fill GitHub's noisy concatenation. Now that
the bot owns the body, the default value of
`squash_merge_commit_message` matters only for the (rare) case where
someone clicks the native squash button in the GitHub UI instead of
applying the `automerge` label. Pick the value that produces the
least-bad output in that fallback path:

```bash
# PR_TITLE leaves the body empty (subject only); safest fallback —
# matches the maintainer-paste-blank semantics that have been in
# place since #290.
gh api -X PATCH repos/aidanns/agent-auth \
  -f squash_merge_commit_message=PR_TITLE
```

```bash
# COMMIT_OR_PR_TITLE pre-fills the body with the PR commit messages
# concatenated — the noisy default that #290 specifically
# suppressed. Do NOT pick this unless every contributor reliably
# rebases their PR commits down to the body shape they want in
# git log.
```

```bash
# Confirm the new value:
gh api repos/aidanns/agent-auth --jq '.squash_merge_commit_message'
```

This step is **optional** — leaving the value at `BLANK` continues
to work because the bot ignores it (the API call passes
`commit_message` explicitly). Flip it only after a release cycle of
bot-mediated merges has shown the bot is reliable.

## Optional: disable the native squash button

After a release cycle of bot-mediated merges, the maintainer can
disable the native squash button in repo settings so the bot is the
*only* merge path:

```bash
gh api -X PATCH repos/aidanns/agent-auth \
  -F allow_squash_merge=false
```

The bot's merge call uses the merge endpoint directly and does not
depend on the UI button being available. This is a tightening
rather than a change in flow; the bot continues to function
identically. Restore the button by setting `allow_squash_merge=true`
if a regression is observed.

## Verifying the bot end-to-end

After steps 1–4, the next PR merged via the `automerge` label
should produce:

- A squash commit on `main` whose body (`git log -1 --format=%B`)
  matches the contents of the PR's `==COMMIT_MSG==` block exactly,
  including the `Signed-off-by:` trailer.
- A `Claude: Merged via bot.` comment on the PR (posted by the
  `agent-auth-merge-bot` App identity).
- The `dco` workflow staying green on `main` because the
  `Signed-off-by:` trailer round-trips into the squash commit.
- The `Closes #N` trailer in the block closing the linked issue
  on merge.

If any of those signals is wrong, the most likely cause is a setup
gap: missing secret, App not installed on the repo, or the App not
yet added to the `main` ruleset bypass-actor list.

## Failure modes the bot surfaces

Each `Claude: Cannot merge — <reason>` comment on a PR maps to one
of:

- **Required check failed**: a check listed in the `main` ruleset
  is `FAILURE` / `TIMED_OUT` / `CANCELLED`. Fix the check, push,
  and the `check_suite: completed` retrigger will run the bot
  again.
- **`==COMMIT_MSG==` block extraction failed**: the PR body has
  zero or two-or-more `==COMMIT_MSG==` markers. Edit the PR body
  to leave exactly one block.
- **`==COMMIT_MSG==` block has no `Signed-off-by:` trailer**: the
  block parses but lacks DCO. Add `Signed-off-by: Name <email>` as
  the last line of the block.
- **GitHub merge API rejected the call**: surfaced as the literal
  API error string. The most common cause is the App not being a
  bypass actor on the `main` ruleset (returns
  `405 Pull Request is not mergeable`).

The label stays applied through every failure so the recovery path
is "fix the underlying problem and push" — no need to remove and
re-add the label.
