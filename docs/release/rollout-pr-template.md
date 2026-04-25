<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Rollout: PR template + commit-msg block lint

Tracking-issue rollout notes for #290 (sub-issue of #289). Records the
maintainer-side steps that sit outside the PR's diff and the interim
mechanics until the merge bot (#291) lands.

## Maintainer action required before merging #290

The lint and the PR template assume the repo's squash-merge dialog
defaults to an **empty** body, so the maintainer can paste the
`==COMMIT_MSG==` block in by hand without first deleting GitHub's
default concatenation of every PR commit. This is a single repo
setting that must be flipped before merging this PR:

1. **`squash_merge_commit_message: BLANK`** — set on the repository
   via the GitHub API or UI:

   ```bash
   gh api -X PATCH repos/aidanns/agent-auth \
     -f squash_merge_commit_message=BLANK
   ```

   Or via the UI: *Settings → General → Pull Requests → Allow squash
   merging → Default to a blank commit message*. Confirm afterwards:

   ```bash
   gh api repos/aidanns/agent-auth --jq '.squash_merge_commit_message'
   # should print: BLANK
   ```

The other two values
[`squash_merge_commit_title`](https://docs.github.com/en/rest/repos/repos#update-a-repository)
takes are intentionally **left alone**: the title default
(`PR_TITLE`) is correct — the PR title is the contributor's signal
and matches the lint.

## Why blank-by-default

Without `BLANK`, GitHub concatenates every PR commit's message into
the squash-merge body. That picks up scratch commits ("address review
comments", "rebase", "fix typo") and pollutes `git log`. Setting the
default to `BLANK` lets the maintainer paste in only the contents of
the contributor's `==COMMIT_MSG==` block — which is the audited,
linted, contributor-curated body — and nothing else.

## Interim merge procedure

While #291 is pending, the maintainer at merge time:

1. Opens the squash-merge dialog on the PR.
2. Confirms the title is the PR title (auto-filled — the
   `pr-title` lint guarantees its prefix).
3. Copies the contents of the PR's `==COMMIT_MSG==` block
   (everything between the two markers, exclusive — the lint
   guarantees this parses as a clean commit body) into the
   "commit message" field.
4. Clicks *Confirm squash and merge*.

Releases are now driven by the YAML schema introduced in #295 and the
release-PR workflow introduced in #296 (ADR 0041). The squash-merge
subject doesn't need to be translated for the release to fire — the
release version is computed from `changelog/@unreleased/*.yml`
entries directly.

## Acceptance for the rollout step

- `gh api repos/aidanns/agent-auth --jq '.squash_merge_commit_message'`
  prints `BLANK`.
- The first PR merged after #290 lands cleanly with a body that
  matches the `==COMMIT_MSG==` block content (visible in
  `git log -1 --format=%B`).

## Follow-up — once #291 lands

The merge bot in [`.github/workflows/merge-bot.yml`](../../.github/workflows/merge-bot.yml)
takes over the `==COMMIT_MSG==` paste step. Cutover steps for the
maintainer:

1. Complete the App-and-secrets setup in
   [`docs/release/merge-bot-setup.md`](merge-bot-setup.md). The bot
   is dormant until those four steps are done.
2. From the next PR onward, apply the `automerge` label instead of
   pasting the block by hand. The bot calls the merge API on
   `pull_request: labeled`, with a `check_suite: completed`
   retrigger covering the case where the label is applied before
   the last required check goes green.
3. Confirm end-to-end on the first bot-mediated merge:
   `git log -1 --format=%B` on `main` should match the merged PR's
   `==COMMIT_MSG==` block contents exactly (sign-off included),
   and the `Closes #N` trailer should have closed the linked
   issue.
4. The `squash_merge_commit_message: BLANK` setting can stay in
   place — the bot ignores it (it passes `commit_message`
   explicitly). The merge-bot setup doc covers the optional
   follow-on flips (`PR_TITLE` default; disabling the native
   squash button after a release cycle of bot-mediated merges).

Work-issues / CI agents stop calling `gh pr merge --auto --squash`
and instead apply the `automerge` label
(`gh pr edit <pr> --add-label automerge`). The label is the single
"ready to merge" signal both maintainer and automation use.

## Follow-ups

- #291 — merge bot pastes the `==COMMIT_MSG==` block automatically;
  removes step 3 of the interim procedure. **Now landed — see the
  cutover steps above.**
- #295 — bot-mediated `version_logic` consumes the new prefix set
  directly; removes the prefix-translation step.
- #298 — activates `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` markers.
