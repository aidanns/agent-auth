<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0037 — Palantir-style commit prefixes + PR `==COMMIT_MSG==` block

## Status

Accepted — 2026-04-25.

Replaces the prefix half of the "Use Conventional Commit messages"
rules previously documented in `CLAUDE.md` (default Conventional
Commits set: `feat`, `fix`, `perf`, `revert`, `docs`, `style`,
`chore`, `refactor`, `test`, `build`, `ci`).

`.releaserc.mjs` `releaseRules` is being decommissioned independently
by #296; this ADR does not touch it. The release-impact mapping in
this ADR is what #295's bot-mediated `version_logic` will consume.

## Context

`#289` introduces a bot-mediated PR authoring surface where the
contributor writes the squash-merge commit body in the PR description
rather than in the PR's commit history. Two pieces of policy fall
out of that and were left for sub-issues to settle:

1. **Which commit-type prefixes do we accept?** The default
   Conventional Commits set has known noise: `feat:` vs. `feature:`,
   `chore:` swallowing routine deps + tooling + non-user-facing
   refactors, `refactor:`/`style:`/`build:`/`ci:`/`test:` blurring
   the audience signal in `CHANGELOG.md`. Palantir's open-source
   convention (`feature`, `improvement`, `fix`, `break`,
   `deprecation`, `migration`, `chore`) cuts the set down to types
   that map to user-visible release notes and explicit lifecycle
   states.
2. **Where does the contributor write the squash-merge body?** The
   current convention asks contributors to write a clean commit and
   rely on the squash-merge dialog defaulting to "all commits
   concatenated". That picks up scratch commits ("address review
   comments", "fix typo") and produces a noisy `git log` on `main`.
   The `==COMMIT_MSG==` block in the PR template lets the
   contributor author the body once, and the merge bot (#291) will
   eventually paste it verbatim into the squash-merge dialog.

This ADR records the prefix choice, the release-impact mapping that
falls out of it, and the interim mechanics until #291 lands.

## Considered alternatives

### Keep the existing Conventional Commits default set

**Rejected** because:

- The default set's release-impact ambiguity (e.g. `chore:` vs.
  `build:` vs. `ci:`) was already a recurring judgment call in
  `CONTRIBUTING.md` § *Picking a type*. The Palantir set drops the
  ambiguous types entirely.
- Default Conventional Commits has no first-class type for
  *deprecation* or *migration* — both of which the project models as
  patch-level user-visible events that warrant a CHANGELOG line.

### Hybrid (keep `feat`/`fix` aliases for muscle-memory)

**Rejected** because:

- A lint that accepts both `feat:` and `feature:` produces an
  inconsistent CHANGELOG. Either we rewrite at lint time (extra
  surface) or we tolerate the drift.
- Better to flip the convention atomically: this PR is the cutover
  point.

### Author the squash-merge body via a comment trailer rather than a fenced block

**Rejected** because:

- The bot has to find the body. A reserved fenced block
  (`==COMMIT_MSG==` … `==COMMIT_MSG==`) is unambiguous and survives
  Markdown rendering on the PR page. A comment-style marker
  (`<!-- COMMIT_MSG -->`) is invisible to the contributor on the
  rendered PR and easy to delete by accident.
- The fenced block also lets the lint validator scope its checks
  (line-wrap, no-markdown, trailer parsing) to a clearly delimited
  region rather than to "the whole PR body minus some heuristics".

## Decision

1. **Accepted PR-title prefixes** (the lint enforces this exact set;
   optional `(scope)` still permitted, e.g. `feature(ci): …`):

   | Prefix         | Release impact (carried into #295)         |
   | -------------- | ------------------------------------------ |
   | `feature:`     | minor bump                                 |
   | `improvement:` | patch bump                                 |
   | `fix:`         | patch bump                                 |
   | `deprecation:` | patch bump                                 |
   | `migration:`   | patch bump                                 |
   | `break:`       | major bump (demoted to minor while in 0.x) |
   | `chore:`       | no release entry                           |

   No `feat:`, `perf:`, `revert:`, `docs:`, `style:`, `refactor:`,
   `test:`, `build:`, `ci:`. The cases those types covered map onto
   the new set as: user-visible perf wins → `improvement:`; reverts
   → the type the original commit would have had (lint doesn't care
   that it's a revert); docs/style/refactor/test/build/ci → `chore:`
   when not user-visible, otherwise the user-visible type wins.

2. **PR template carries a `==COMMIT_MSG==` … `==COMMIT_MSG==` fenced
   block** that the contributor fills with the squash-merge commit
   body. A clearly separated `## Review notes` section holds the
   test plan, screenshots, and reviewer notes — explicitly marked
   as **not** entering git history. The lint validates the block;
   the merge bot (#291) will paste it into the squash-merge dialog
   verbatim.

3. **Interim mechanics** until #291 lands: the maintainer sets the
   repo-level `squash_merge_commit_message: BLANK` so the
   squash-merge dialog defaults to an empty body, and pastes the
   `==COMMIT_MSG==` content in by hand at merge time. This keeps
   `main`'s git log clean during rollout. Documented in
   `docs/release/rollout-pr-template.md`.

## Consequences

- `CONTRIBUTING.md` and `CLAUDE.md` are rewritten to drop the
  Conventional Commits default set and adopt the Palantir set.
  Contributors muscle-memorying `feat:` will get a hard CI failure
  on the PR-title lint until they relearn `feature:`.
- `CHANGELOG.md` will start using the new prefix set on the next
  release-bumping commit. Older entries stay as-is — semantic-release
  prepends.
- The `==COMMIT_MSG==` block adds a contributor authoring step that
  did not previously exist. The PR template's worked example covers
  it. Until #291, the maintainer also has to copy the block content
  into the squash-merge dialog manually — surfaced in the PR body
  template + the rollout doc.
- A broken validator script could in principle gate PRs green by
  exiting 0 on every input. The validator self-test job runs every
  fixture (one passing, several failing) on the same workflow run,
  so a regression in the validator immediately fails CI rather than
  silently approving everything.
- The release-impact mapping is documented here but **not enforced
  by `.releaserc.mjs`**; that file is being decommissioned by #296
  in favour of #295's bot-mediated version logic. Until #295 lands,
  semantic-release continues to drive releases off the *old* prefix
  set on `main`'s git log. This is fine because:
  - The `chore(release):` commits semantic-release writes use
    `chore:` which is in both sets.
  - Until #291 + #295 are wired in, the maintainer is responsible
    for translating the new-prefix PR title into the appropriate
    old-prefix squash-merge subject if a release is desired
    (e.g. `feature: X` PR -> `feat: X` squash subject). This is a
    short-lived burden — see `docs/release/rollout-pr-template.md`.

## Follow-ups

- #291 — merge bot pastes the `==COMMIT_MSG==` block into the
  squash-merge dialog. Removes the maintainer-paste step and the
  prefix-translation burden above.
- #295 — bot-mediated `version_logic` consumes the release-impact
  mapping in this ADR and replaces `.releaserc.mjs`'s `releaseRules`.
- #296 — decommissions `.releaserc.mjs`.
- #298 — activates `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` markers
  (placeholders are inert in the template until then).
