<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan 0001 — PR template + commit-msg block lint (#290)

Sub-issue of #289. Establish the PR template's `==COMMIT_MSG==` authoring
surface and the lint that gates it.

## Scope

- Restructure `.github/PULL_REQUEST_TEMPLATE.md` with a fenced
  `==COMMIT_MSG==` block, a clearly separated `## Review notes`
  section, and inert placeholders for the `==CHANGELOG_MSG==` /
  `==NO_CHANGELOG==` markers (#298 owns the active behaviour).
- Add `.github/workflows/pr-lint.yml` enforcing
  - PR title against the new Palantir-style prefix allowlist
    (`feature, improvement, fix, break, deprecation, migration, chore`).
  - The `==COMMIT_MSG==` block: present once, ≤ 72 char wrap, no
    markdown headings/lists/checkboxes inside, `BREAKING CHANGE:`
    only on the last non-`Signed-off-by:` line, trailers parse per
    git-trailer format.
- Self-test the commit-msg validator against fixtures in
  `.github/workflows/tests/pr-lint-fixtures/`.
- Update `CLAUDE.md` and `CONTRIBUTING.md` to reflect the new prefix
  set + `==COMMIT_MSG==` convention; cross-reference the worked
  example.
- Document the maintainer-side rollout step
  (`squash_merge_commit_message: BLANK`) in
  `docs/release/rollout-pr-template.md`.
- ADR capturing the convention switch (Palantir prefixes + commit-msg
  block).

## Out of scope

- Merge bot — #291.
- `==CHANGELOG_MSG==` / `==NO_CHANGELOG==` enforcement — #298.
- Changelog YAML lint — separate sub-issue.
- `.releaserc.mjs` — being decommissioned by #296.

## Design and verification

- **Verify implementation against design doc** — N/A; this is a
  policy/tooling change, not a service surface. Design impact is
  captured in the ADR and in CONTRIBUTING.md instead.
- **Threat model** — N/A. The PR template + lint are not on the
  attacker surface (they gate the contributor authoring path, not
  runtime). The worst failure mode is a noisy CHANGELOG, not a
  security issue.
- **Post-incident review (PIR)** — N/A; not a vulnerability fix.
- **Architecture Decision Records** — write
  `design/decisions/0037-palantir-commit-prefixes-and-commit-msg-block.md`
  capturing (a) why the Palantir-style prefixes replace the
  Conventional Commits default set, (b) why the squash-merge body
  authoring moves into the PR template via `==COMMIT_MSG==`, and
  (c) the interim `squash_merge_commit_message: BLANK` step until
  the merge bot lands.
- **Cybersecurity standard compliance** — N/A; out of scope for
  contributor-facing policy.
- **Verify QM / SIL compliance** — N/A; SIL is product-side.

## Implementation

1. ADR `0037-palantir-commit-prefixes-and-commit-msg-block.md`.
2. Restructure `.github/PULL_REQUEST_TEMPLATE.md` per spec above.
3. Add the validator script
   `scripts/validate-commit-msg-block.py` (Python, no extra deps —
   project standardises on Python and stdlib-only is the no-deps
   rule from CLAUDE.md). Reads PR-body markdown from a file path on
   argv. Exits non-zero with a human-readable error on failure.
4. Add fixtures under `.github/workflows/tests/pr-lint-fixtures/`:
   - `valid-minimal.md` — bare body with a clean COMMIT_MSG block
     and trailers.
   - `valid-breaking.md` — body with `BREAKING CHANGE:` as the last
     non-`Signed-off-by` line.
   - `invalid-no-block.md` — missing `==COMMIT_MSG==` markers.
   - `invalid-multiple-blocks.md` — two `==COMMIT_MSG==` regions.
   - `invalid-too-wide.md` — line > 72 chars in the block.
   - `invalid-markdown.md` — markdown heading inside the block.
   - `invalid-list.md` — bullet list inside the block.
   - `invalid-breaking-not-last.md` — `BREAKING CHANGE:` followed
     by a non-trailer line.
   - `invalid-bad-trailer.md` — malformed trailer.
5. Add `.github/workflows/pr-lint.yml`. Two jobs:
   - `pr-title` — runs `amannn/action-semantic-pull-request` with
     the explicit `types:` allowlist (no defaults).
   - `pr-body-commit-msg` — runs the validator against the live
     PR body via `${{ github.event.pull_request.body }}` written
     to a tmp file.
   - `validator-self-test` — runs the validator against every
     fixture and asserts the expected pass/fail outcome. Lives in
     the same workflow so a broken validator can never gate PRs
     green.
6. Update `CLAUDE.md` "Use Conventional Commit messages" section
   with the new prefix set, the release-impact mapping carried
   forward into #295, and the COMMIT_MSG-block convention. Cross-
   reference CONTRIBUTING.md for the worked example.
7. Update `CONTRIBUTING.md`:
   - Replace the "Commit conventions" type table with the new
     Palantir-style prefix list + release-impact mapping.
   - Add a "Writing PRs" section with a worked PR-template
     example. Explain the audience split: `==COMMIT_MSG==` ->
     git log; review notes -> PR review surface only. Document
     the interim maintainer-paste step.
8. Add `docs/release/rollout-pr-template.md` documenting the
   repo-setting change (`squash_merge_commit_message: BLANK`)
   that the maintainer applies before merge. Surface the same
   requirement in the PR body so it can't be missed.

## Post-implementation standards review

- **Coding standards (`coding-standards.md`)** — Python validator
  uses `argparse`, type-annotated functions, descriptive verb
  names. No raw tuples for structured returns.
- **Service design (`service-design.md`)** — N/A; no service
  surface added.
- **Release and hygiene (`release-and-hygiene.md`)** — the new
  prefix set is documented in `CONTRIBUTING.md` (the canonical
  source for contributor-facing policy now that `.releaserc.mjs`
  is being decommissioned by #296). `CLAUDE.md` cross-references
  it.
- **Testing standards (`testing-standards.md`)** — validator
  fixtures cover both passing and each failure mode. The
  `validator-self-test` workflow job exercises all fixtures
  and is co-located with the gate it protects.
- **Tooling and CI (`tooling-and-ci.md`)** — `task pr-lint` does
  not need to exist (no local invocation surface; the gate is
  PR-only). The validator script is invokable directly. CI gating
  via `.github/workflows/pr-lint.yml`. amannn action read-only,
  off the release path -> floating-major tag is acceptable per
  the existing pinning policy. The body validator runs in the same
  workflow so a broken validator can never gate PRs green.

## Acceptance

- PR template renders with the new structure.
- A PR violating the format (e.g. test plan inside the
  `==COMMIT_MSG==` block) fails CI.
- A clean PR (this one) passes.
- CONTRIBUTING.md has a worked example.
- `squash_merge_commit_message: BLANK` is documented in
  `docs/release/rollout-pr-template.md` and surfaced in the PR
  body for maintainer action before merge.
