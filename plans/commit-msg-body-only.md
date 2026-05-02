<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Commit-msg block contains body only (issue #478)

## Problem

Authors currently write the PR's `==COMMIT_MSG==` block as
"subject + blank + body + trailers". The merge bot pastes the entire
block as `commit_message` while independently setting `commit_title`
from the PR title. GitHub renders a squash commit by joining
`commit_title + blank + commit_message`, so every recent merge has
the subject duplicated — once in the subject line and again as the
first line of the body. Examples from `main`: `b69f7e2`, `d033861`,
`bca4070`.

The PR title is already authoritative for the squash subject (the
title-validator forces them to match). The redundancy in the block
is what makes the duplication possible.

## Decision

Cut the convention down to "body and trailers only". The subject
lives only in the PR title and is rendered into `commit_title` by
the merge API. Hard cutover: validator, bots, template and docs all
flip in one PR. The validator's failure message tells any author
who carries the old shape exactly what to do.

## Affected components

01. **`scripts/validate-commit-msg-block.py`**
    - Drop the title-aware first-line subject-duplication check
      (`check_first_line_not_subject_dup` and the `--title` plumbing
      that feeds it).
    - Add a no-leading-subject check: the first non-blank content
      line MUST NOT match
      `^(feature|improvement|fix|deprecation|migration|break|chore)(\([^)]+\))?: .+$`
      (the project's PR-title prefix allowlist per ADR 0037). The
      failure message is exactly the string the issue body specifies.
    - Trailer parsing, BREAKING CHANGE positioning, line-width,
      contiguity, and blank-before-trailers checks stay as-is.
    - `_TITLE_AWARE_SELF_TEST_CASES` (which only covered the
      subject-dup check) is removed; the verbose-body self-test
      stays.
02. **`.github/workflows/tests/pr-lint-fixtures/`**
    - Drop the leading subject line + the blank line that followed
      it from every existing `valid-*.md` and from the
      `invalid-*.md` fixtures whose body still parses meaningfully
      after the strip. Fixtures that exercise other failure modes
      (empty block, missing block, wide line, …) are left alone
      when the strip would invalidate the failure mode under test.
    - Add `invalid-leading-subject-line.md` — a body whose first
      non-blank line is a CC-shaped subject (e.g.
      `improvement(ci): wire the foo into the bar`). Pins the new
      no-leading-subject check.
    - The valid fixtures already cover the body-only shape
      implicitly (they were body-only after the subject strip), so
      no new `valid-*.md` fixture is needed beyond the strip.
03. **`.github/workflows/pr-lint.yml`**
    - Drop the `--title "${PR_TITLE:-}"` argument from the
      pr-body-commit-msg job's invocation. The `--title` flag is
      gone; passing it would error.
    - Update the top-of-file comment (rule 3 listing) so
      "no first-line subject duplication" becomes
      "no leading subject line".
04. **`tests/test_extract_commit_msg_block.py`**
    - The `test_extract_block_returns_content_between_markers` test
      hard-codes the expected content of `valid-minimal.md`. Update
      the expected string to match the post-strip body.
05. **`scripts/changelog/build_release.py`**
    - Already body-only (the renderer emits `Improvements:` /
      `Features:` / etc. as section headings, not a CC-shaped
      subject line). No change needed.
06. **`scripts/changelog/bot.py`**
    - The issue text references this file but the bot does not
      author a `==COMMIT_MSG==` block — it writes
      `changelog/@unreleased/*.yml` files via the
      `==CHANGELOG_MSG==` marker. No change needed; recorded here
      so the absence is intentional, not an oversight.
07. **`.github/workflows/dependabot-adapter.yml`**
    - Drop the leading "Routine dependency upgrade authored by
      Dependabot." line + the blank that followed it from the
      synthesised block; the body becomes
      `See the PR description for upstream release notes.\n\nSigned-off-by: dependabot[bot] <support@github.com>`.
    - Update `valid-dependabot-adapter.md` to match.
08. **`.github/PULL_REQUEST_TEMPLATE.md`**
    - The block is currently empty between the markers; the rules
      comment immediately above it does not currently mention a
      subject. Update the rules comment so the new "body only"
      contract is explicit (a single bullet noting the PR title
      is the squash subject and the block is body + trailers).
09. **`.github/workflows/merge-bot.yml`** top-of-file comment
    - Tighten the existing description so it reads "the body
      content of the squash-merge commit" rather than implying
      the block is the full squash body. The bot's mechanics
      don't change.
10. **`design/decisions/0038-merge-bot-via-github-app.md`**
    - Add an addendum dated today: the
      `==COMMIT_MSG==` convention has narrowed from
      "subject + body + trailers" to "body + trailers only".
      Preserve the historical decision context.
11. **`docs/release/merge-bot-setup.md`**
    - Update the "What the bot does" section so step 4's
      `commit_title` / `commit_message` description matches the
      new shape.
12. **`CONTRIBUTING.md`**
    - The "Writing PRs" → worked examples section still shows
      blocks with leading subjects. Drop the leading subject line
      - blank from each example, and update the surrounding
        prose to describe the body-only shape.

## Tests

- Validator self-test loop accepts every updated `valid-*.md` and
  rejects every `invalid-*.md` (`pr-lint.yml`'s
  `validator-self-test` job; equivalent local invocation is
  iterating fixtures with `python3 scripts/validate-commit-msg-block.py <fixture>`).
- New `invalid-leading-subject-line.md` fixture pins the new
  check.
- `tests/test_extract_commit_msg_block.py` still passes against
  the updated `valid-minimal.md`.
- `scripts/changelog/tests/test_build_release.py` still passes —
  the renderer's output is body-only and the validator accepts it.

## Migration

Hard cutover. Open PRs at the time of the switch will fail
validation until rebased to strip the subject line; the
validator's error message tells the author what to do. The repo
is low-traffic enough that the friction is near-zero.

## Self-test of THIS PR's body

THIS PR's `==COMMIT_MSG==` block is authored in the new body-only
shape from the start — the validator THIS PR ships is what
validates THIS PR's body, so a leading subject line would self-
reject.

## Plan-template steps

- Design verification: ADR 0038 carries the historical decision;
  the addendum captures the narrowed shape so the rationale
  survives beyond commit messages.
- Coding standards (`coding-standards.md`): no new types;
  validator change is one regex + a new helper.
- Service design (`service-design.md`): N/A — CI scripts only.
- Testing standards (`testing-standards.md`): the new check has a
  dedicated `invalid-leading-subject-line.md` fixture; existing
  valid fixtures cover the no-leading-subject path implicitly.
- Tooling and CI (`tooling-and-ci.md`): the
  `validator-self-test` job exercises the change on every PR.
- Release and hygiene (`release-and-hygiene.md`): a hand-authored
  changelog YAML lands on the branch (the changelog bot does not
  auto-author entries).
