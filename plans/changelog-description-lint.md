<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Changelog `description:` style lint (#407)

Closes #407.

## Summary

Tighten the PR-time changelog lint
(`scripts/changelog/lint.py`) to enforce a terse, single-sentence
`description:` field on every newly-added `changelog/@unreleased/*.yml`
entry:

- Hard cap: `description:` must be at most 25 words after whitespace
  normalisation.
- Hard cap: `description:` must be a single sentence — exactly one
  terminal `.`, `!`, or `?` at the end, with no embedded sentence
  terminator outside a small abbreviation allowlist (`e.g.`, `i.e.`,
  `etc.`, `cf.`, `vs.`, `vs`, single-letter initials, …).
- Helpful error: when either cap is exceeded, the lint message
  points the author at the PR's `==COMMIT_MSG==` block as the
  authoritative home for the longer prose, mirroring the audience
  split documented in the issue body.

The `description:` field feeds two user-facing audiences
(CHANGELOG.md / GitHub release notes via `render_release_notes`,
and the release-PR `==COMMIT_MSG==` block via
`render_commit_msg_block`). Both want a one-liner; archaeology lives
on the originating PR's hand-authored `==COMMIT_MSG==` block.

## Out of scope (forward-only enforcement)

- Re-writing existing `changelog/<version>/*.yml` entries on `main`.
  Many would fail the new lint; the issue explicitly calls for
  forward-only enforcement so those stay as historical record.
- Schema changes — no new `release_summary:` field. The
  `description:` field's semantics tighten; nothing else moves.
- The two existing `changelog/@unreleased/*.yml` entries
  (`pr-425`, `pr-430`) — the lint only checks files *added* in the
  PR being scanned, so historical (already-on-`main`) `@unreleased/`
  entries are not retroactively re-validated. The same forward-only
  property is what keeps `release-PR` rebases of older entries from
  failing.

## Design verification

No new ADR — this is a lint tightening, not a flow change. The
audience split (terse `description:` vs. verbose
`==COMMIT_MSG==`) is already structurally present in the
project; the lint formalises an existing convention rather than
introducing a new one.

Decisions captured here:

- **Lint location** — extended `scripts/changelog/lint.py` (not
  `version_logic.parse_entry_file`). Keeping the parser permissive
  preserves its ability to read historical entries unchanged; the
  PR-time check sits at the lint layer where forward-only
  enforcement is already the established mode.
- **Wiring** — added a new `check_description_style` step in
  `run_lint`, applied to the *added-in-this-PR* file list (same
  scope as `check_file_naming`). Re-uses the existing
  `LintReport.fail` aggregation so all findings still land in one CI
  run.
- **Description normalisation** — collapse every whitespace run
  (including newlines from `|` block scalars) into a single space,
  then strip. The 25-word cap counts the resulting tokens via
  `len(normalised.split())`. The single-sentence check operates on
  the normalised string.
- **Abbreviation allowlist for sentence detection** — `e.g.`,
  `i.e.`, `etc.`, `cf.`, `vs.`, plus a single-letter initial pattern
  (`A.`, `B.`, …). Anything else inside the description that ends
  with `. ` (period + space) is treated as a sentence boundary.
  Documented in the lint module docstring + the helper's docstring.
  This covers every embedded period that legitimately appears in
  one-line user-facing release notes; longer abbreviation runs
  belong in the `==COMMIT_MSG==` block.
- **Re-use via release-impact-comment / release-pr workflows** —
  not in scope. Those consume the YAML for surface rendering, not
  authorship validation; tightening here is enough to stop new
  verbose entries from landing.

## Implementation steps

1. Add a `MAX_DESCRIPTION_WORDS = 25` constant + a private
   `_check_description_style(entry, report)` helper to
   `scripts/changelog/lint.py`. The helper:
   - Normalises whitespace.
   - Counts words; fails if `> 25`.
   - Counts sentence-ending punctuation; fails if there isn't
     exactly one terminal `.`, `!`, or `?` at the end of the
     normalised string.
   - Walks the description for embedded `. ` / `! ` / `? `
     occurrences, skipping ones immediately preceded by an entry
     in the abbreviation allowlist; fails with a pointer at the
     `==COMMIT_MSG==` block when any survives.
2. Add a `check_description_style(files, report)` wrapper that
   re-parses each file (skipping ones whose schema check already
   failed) and runs the helper. Wire it into `run_lint` against
   the *added* file list.
3. Document the rule in the lint module docstring (point 5,
   alongside the existing four). Note the forward-only scope.
4. Update `CONTRIBUTING.md` → "Changelog entries
   (`changelog/@unreleased/*.yml`)" with:
   - The two caps (≤ 25 words, single sentence).
   - The terse-vs-verbose example using `pr-383` (the issue's
     canonical case).
   - The pointer to the PR's `==COMMIT_MSG==` block as the home
     for the longer prose.
5. Add unit tests under
   `scripts/changelog/tests/test_lint.py`:
   - Passing case: a short single-sentence description.
   - Failing cases: > 25 words, multi-sentence, no terminal
     punctuation.
   - Passing cases that exercise the abbreviation allowlist
     (`e.g.`, `i.e.`, `etc.`, single-letter initials).
   - Passing case: a description with embedded newlines from a
     `|` block scalar — normalised whitespace collapses cleanly.
6. Add a passing changelog entry for this PR
   (`changelog/@unreleased/pr-<N>-changelog-description-lint.yml`)
   that itself satisfies the new lint — meta-validation that the
   lint behaves on real terse copy.

## Post-implementation standards review

- `coding-standards.md` — naming/types: `_check_description_style`
  takes a `ChangelogEntry`, returns `None`, mutates the report.
  Constant `MAX_DESCRIPTION_WORDS` is named in units (words).
- `service-design.md` — n/a, no service surface changes.
- `release-and-hygiene.md` — the lint is a tightening of the
  existing `changelog-lint` job; CHANGELOG.md / release-notes
  rendering surface unchanged.
- `testing-standards.md` — tests exercise the public `run_lint`
  surface against fixture YAMLs (same shape as the existing
  `test_lint.py` tests), not the private helper, so the test
  isn't coupled to the helper's internal structure.
- `tooling-and-ci.md` — runs inside the existing `changelog-lint`
  workflow; `scripts/changelog/test.sh` covers the new tests.
