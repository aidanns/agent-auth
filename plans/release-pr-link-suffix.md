<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Append `(#N)` PR-link to release-note entries (#411)

Closes #411.

## Summary

Each rendered release-note entry should end with `(#N)` so a reader of
`CHANGELOG.md`, the GitHub release body, or the release PR's
`==COMMIT_MSG==` block can click straight through to the originating
PR for the verbose context that the terse `description:` field
deliberately omits (see #407, the audience-split source of the
information-loss problem this fixes).

Single-point append: derive `<N>` from the YAML filename via the
existing `ENTRY_FILENAME_PATTERN` (`^pr-(\d+)-.+\.yml$`) so all three
audiences inherit the suffix from one helper. Source from the filename
rather than `links:` because the convention is single-PR and machine-
readable; the `links:` array is human-authored and may include issues,
multiple PRs, or be absent.

## Design verification

No new ADR. The change is mechanical — a renderer-only suffix that
GitHub auto-renders to a clickable PR link in all three surfaces
(commit body, CHANGELOG.md viewed on github.com, release page). The
audience-separation rationale already lives in #407's design decision.

## Implementation

### 1. Renderer change (`scripts/changelog/build_release.py`)

- Add `_pr_link_suffix(entry: ChangelogEntry) -> str` that returns
  ` (#N)` when the YAML filename matches `ENTRY_FILENAME_PATTERN`,
  else `""`. Single helper imported from `version_logic` for the
  pattern (already exposed).
- Append the suffix in three render paths:
  - `_render_changelog_bullet` — append to the *first* (bullet) line
    so the suffix lands at the end of the visible bullet text.
  - `_render_notes_bullet` — same shape for the GitHub release body.
  - `render_commit_msg_block` — append per-entry inside the
    semicolon-joined paragraph, so each entry retains its own
    suffix even when collapsed into prose.
- The fail-soft skip (filename doesn't match) is the safety net for
  legacy / hand-edited entries; the new lint check below makes this
  case impossible at PR-time.

### 2. Wrap algorithm (`_wrap_paragraph`)

- Add a "PR-suffix" rule sibling to the existing numbered-reference
  rule: tokens matching `^\(#\d+\)$` (and the trailing `.` /
  `)`-flavoured variants) must never land alone at the start of a
  wrapped line. When the suffix would otherwise overflow the current
  line, drag the preceding token down with it (mirrors the existing
  `is_numeric and len(current_tokens) >= 2` branch). Soft-overflow
  fallback when the line has nothing to drag.
- This keeps the suffix bound to the entry's last visible word, so a
  reader's eye doesn't lose the link half a line away from the entry
  it belongs to.

### 3. Filename-pattern lint (`scripts/changelog/lint.py`)

- Add `check_present_file_naming(present_files, report)` that fails
  any `changelog/@unreleased/*.yml` whose filename doesn't match
  `ENTRY_FILENAME_PATTERN`. Wire it into `run_lint` after the
  existing `check_file_naming` (which only sees files added in the
  current PR — this new check covers files already on `main`).
- The error message points at the offender and explains the
  requirement so a contributor running `task changelog:add` sees a
  self-explanatory failure.

### 4. Tests

Add to `scripts/changelog/tests/test_build_release.py`:

- `test_render_changelog_section_appends_pr_link_suffix` —
  one entry, assert the bullet line ends with `(#100)`.
- `test_render_release_notes_appends_pr_link_suffix` —
  same shape over the GitHub-release surface.
- `test_render_commit_msg_block_appends_pr_link_suffix_per_entry` —
  multiple entries, assert each `(#N)` survives the
  semicolon-joining.
- `test_render_commit_msg_block_does_not_wrap_before_pr_link_suffix` —
  long single-bullet description crafted so the buggy wrapper would
  drop `(#383)` alone onto a wrapped line; assert the suffix stays
  bound to the preceding token AND lines remain ≤ 72 chars (reuse
  `_assert_block_satisfies_validator`).
- `test_render_changelog_bullet_skips_suffix_when_filename_unconventional` —
  fail-soft: a `ChangelogEntry` with `source_path` not matching the
  pattern (e.g. `unrelated.yml`) gets no suffix.

Add to `scripts/changelog/tests/test_lint.py`:

- `test_run_lint_fails_when_unreleased_file_lacks_pr_prefix` —
  drop a `legacy.yml` into `changelog/@unreleased/` already on main
  (committed before the PR), open a PR adding an unrelated file, and
  assert the report fails with the legacy filename in the message.

### 5. Documentation

- Update `CONTRIBUTING.md` § "Changelog entries" with one sentence on
  the auto-suffix so contributors don't try to hand-author it.

## Out of scope

- Backfilling `(#N)` into already-published `CHANGELOG.md` entries.
  Forward-only per the issue.
- Changing the YAML schema; the PR number stays derived from the
  filename.

## Post-implementation standards review

- Coding standards: helper has a verb name (`_pr_link_suffix`),
  signed-off type, no raw tuples.
- Service design: pure-function renderer change, no new config /
  paths / network surface.
- Release/hygiene: changelog YAML hand-authored on the branch;
  `improvement(release):` PR title.
- Testing: tests exercise the public renderer + lint surfaces, not
  the new private helper directly. Long-bullet wrap fixture covers
  the regression vector called out in the issue.
- Tooling/CI: lint is wired into the existing `run_lint` flow; no new
  workflow file. `task changelog:test` is the single-command runner.
