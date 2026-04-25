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

Until #295's bot-mediated `version_logic` lands, semantic-release
continues to drive releases off the **old** Conventional Commits
prefix set on `main`'s git log. If the merged commit needs to fire a
release:

- `feature: …` (new prefix) → paste the body and *also* rewrite the
  squash-merge subject as `feat: …` so semantic-release picks it up.
- `improvement:` / `migration:` / `deprecation:` → rewrite as `fix:`
  for a patch bump (closest behavioural match in the old set).
- `fix:` / `chore:` / `break:` → keep as-is; `fix:` and the implicit
  `BREAKING CHANGE:` footer behave the same in both sets, and
  `chore:` is in the no-release list either way.

This translation step disappears with #295 + #296.

## Acceptance for the rollout step

- `gh api repos/aidanns/agent-auth --jq '.squash_merge_commit_message'`
  prints `BLANK`.
- The first PR merged after #290 lands cleanly with a body that
  matches the `==COMMIT_MSG==` block content (visible in
  `git log -1 --format=%B`).

## Follow-ups

- #291 — merge bot pastes the `==COMMIT_MSG==` block automatically;
  removes step 3 of the interim procedure.
- #295 — bot-mediated `version_logic` consumes the new prefix set
  directly; removes the prefix-translation step.
- #296 — decommissions `.releaserc.mjs`.
- #298 — activates `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` markers.
