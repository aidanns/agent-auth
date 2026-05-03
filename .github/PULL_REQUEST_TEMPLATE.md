<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!--
PR title (what this issue's `pr-title` lint enforces) must use one of:

  feature: | improvement: | fix: | break: | deprecation: | migration: | chore:

Optional `(scope)` is allowed (e.g. `feature(ci): add pr-lint workflow`).
The PR title becomes the squash-merge commit subject.

The `==COMMIT_MSG==` block below becomes the squash-merge commit body —
the body and trailers only, NOT a leading subject line. GitHub renders
the squash commit by joining `commit_title + blank + commit_message`,
and the merge bot sets `commit_title` from the PR title; a subject in
both places renders twice on `main` (issue #478). The validator rejects
a first non-blank line that looks like a Conventional-Commit subject
(e.g. `improvement(ci): wire the foo`).

The `## Review notes` section is for the reviewer only — it does NOT
enter git history. See CONTRIBUTING.md → "Writing PRs" for a worked
example. The split is enforced by .github/workflows/pr-lint.yml.
-->

<!--
Author the squash-merge commit body inside the ==COMMIT_MSG== block
below. Rules (enforced by .github/workflows/pr-lint.yml):

- Body and trailers only — NO leading subject line. The PR title is
  the source of the squash commit's subject.
- Lines wrap at <= 72 chars.
- No markdown headings (#), task checkboxes (- [ ] / - [x]), or
  image embeds (![alt](url)) inside this block. Plain - / * bullets
  and 1. numbered lists are permitted (kernel/cbea.ms style).
- If a `BREAKING CHANGE:` footer is present, it must be on the last
  non-`Signed-off-by:` line.
- Trailers (`Closes`, `Co-authored-by`, `Signed-off-by`) follow the
  git-trailer format `Token: value`. The bare `Closes #N` (no colon)
  is rejected since #566 — use the canonical `Closes: #N` so it
  matches the shape of every other trailer.
- The trailer block is contiguous: stack `Closes: #N` and
  `Signed-off-by:` with no blank line between them. One blank line
  goes ABOVE the trailer block (between body and trailers), not
  inside it — `git interpret-trailers --parse` treats a blank line
  between trailers as the body/trailer boundary.

The block below is intentionally empty — the lint will fail until
you replace this comment with the body.
-->

<!--
If you (Claude or human) authored the ==COMMIT_MSG== body below, add
a `Co-Authored-By: Claude <model+context> <noreply@anthropic.com>`
trailer between `Closes:` and `Signed-off-by:`. See CONTRIBUTING.md
→ "Writing PRs" → "Claude attribution trailer" for the format and
the four edge-case rules; see ADR 0045 for the rationale.
-->

==COMMIT_MSG==
==COMMIT_MSG==

<!--
Optional changelog markers — pick at most one and uncomment it. The
`Changelog Bot` workflow reads these on every push and either commits
a `changelog/@unreleased/pr-<N>-*.yml` for you (==CHANGELOG_MSG==) or
applies the `no changelog` label so the lint bypasses the file
requirement (==NO_CHANGELOG==).

A. Auto-author the changelog YAML: uncomment the block below and put
   the release-note text between the markers. The bot picks the YAML
   `type:` from the PR-title prefix (`feature:`, `improvement:`,
   `fix:`, `break:`, `deprecation:`, `migration:`). You can hand-edit
   the YAML the bot commits — the bot stops re-writing once any
   non-bot commit touches the file.

       ==CHANGELOG_MSG==
       Replace this line with the release-note text. Markdown allowed.
       ==CHANGELOG_MSG==

B. Opt out of a changelog entry: uncomment the marker line below.
   Required for `chore:` PRs, optional for any PR with no user-visible
   change. The bot adds the `no changelog` label; removing the marker
   on the next push removes the label (only when the bot applied it —
   a maintainer-applied label is preserved).

       ==NO_CHANGELOG==

If you neither use a marker nor hand-author a YAML, `Changelog Lint`
will fail the PR — that's the intentional fall-through path.
-->

## Review notes

<!--
Anything the reviewer needs that should NOT enter git history:
test plan, screenshots, links to design docs, deploy steps, gotchas.
This section is dropped at merge time.
-->

### Test plan

<!-- Checklist of verification steps the reviewer can re-run. Prefer
concrete task commands (e.g. `task check`, `task test`) over prose. -->
