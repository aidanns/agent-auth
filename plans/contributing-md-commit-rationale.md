<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan — CONTRIBUTING.md commit-message rule rationale (issue #562)

## Context and scope

Parent meta-tracker #560 splits the new commit-message rules across two
slices:

- #561 codifies the terse, machine-applied rules in
  `.claude/instructions/commit-messages.md` so every Claude session
  loads them automatically.
- This slice (#562) extends `CONTRIBUTING.md` "Writing release-worthy
  commits" with the human-facing rationale (rule + WHY + anti-pattern)
  plus a second worked counter-example. The expanded prose is what a
  reviewer cites when pushing back on a multi-purpose PR.

The two PRs may merge in either order; a brief broken-link window is
acceptable while #561 lands.

## What changes

### Five new subsections in `CONTRIBUTING.md` "Writing release-worthy commits"

1. **Causal narrative ordering** — lead with the observable behaviour
   the reader could have seen; fold setup into the mechanism, not
   before. Anti-pattern: opening with "X and Y share Z" before the
   reader knows why Z matters.
2. **Brevity** — KEEP / CUT lists. KEEP exact error strings
   (greppable), non-obvious correctness claims, non-obvious failure
   modes, rejected alternatives. CUT diff-recap, narrative
   connectives, success-path confirmations, "behaviour at X is
   unchanged" sentences.
3. **Shouty-marker rule** — folded into the existing backticks
   discussion. `==NO_CHANGELOG==` renders in prose as NO_CHANGELOG;
   the fenced form is reserved for code blocks, not prose, so the
   marker name reads cleanly inside a sentence.
4. **Bullet threshold** — bullets only for parallel sets of 2+
   identical-shape items (tighter than the industry 3+ convention).
   Rationale: parallel sets read clearer as bullets even at 2 items —
   especially file enumerations where exhaustiveness is the point —
   and prose for 2-item parallels reads as a missed structural cue.
5. **Arrows vs prose** — arrows (`->`) for mechanical sub-step chains
   ("query before POST -> no snapshot -> sticky comment"); prose with
   explicit connectives ("so", "because", "which") for the primary
   causal claim. Mixing them inverts the cue.

Each subsection: terse rule + WHY + anti-pattern + (where short) one
example. The TLDR rule lives in `.claude/instructions/commit-messages.md`;
CONTRIBUTING.md is what reviewers cite.

### Second worked counter-example: commit `8859338`

Add alongside (NOT replacing) the existing `7ab4c6a` "Don't restate
the diff" example. The shape mirrors the existing one so reviewers
read both at the same level of abstraction.

The 8859338 message is a useful failure mode to dissect because the
opening two paragraphs are well-shaped — they lead with the
observable orthography tax and the redundant aggregator tax. The
failure mode lives in the third section ("Side effects in the same
PR:") with seven bullets, most of which are diff-recap (the `name:`
stripping, `merge-bot.yml`'s `EXPECTED_WORKFLOWS` update, the doc
rewrite, the standards canary).

The right fix is upstream: the bulleted "while we're here" list
signals the PR is bundling several logical changes. The counter-
example calls out both the bundling smell and the bullet-as-recap
smell.

### Cross-references

- One-line forward link from `CONTRIBUTING.md` to
  `.claude/instructions/commit-messages.md` for the terse rule list,
  placed near the top of "Writing release-worthy commits" so a
  reviewer who only wants the rule list (not the rationale) reaches
  it in one hop.
- Preserve every existing reference to
  [ADR 0037](design/decisions/0037-palantir-commit-prefixes-and-commit-msg-block.md).
  The new prose explicitly sits *alongside* ADR 0037 — ADR 0037 owns
  the prefix allowlist and `==COMMIT_MSG==` block structure; this
  section owns the prose inside.
- The reverse link from `.claude/instructions/commit-messages.md`
  back to `CONTRIBUTING.md` lands in #561.

## Out of scope

- Changes to the terse rule file (`.claude/instructions/commit-messages.md`)
  — that's #561.
- Changes to ADR 0037 itself — the rationale section sits alongside
  it, not inside it.
- Changes to the CI-enforcement table — the new rules are
  convention-only (caught at human review).
- Re-shooting the existing `7ab4c6a` example — it stays, the new
  one is added alongside.

## Design and verification

- **Verify implementation against design doc** — N/A. This is a
  documentation-only change to `CONTRIBUTING.md`; no schema or
  behaviour to diff.
- **Threat model** — N/A. No security-relevant surface changes.
- **Post-incident review (PIR)** — N/A. Not remediating a
  vulnerability.
- **Architecture Decision Records** — N/A. The structural decision
  (prefix allowlist + `==COMMIT_MSG==` block) is already captured in
  ADR 0037; the prose rules sit alongside it as expanded human
  guidance, not a new architectural choice.
- **Cybersecurity standard compliance** — N/A.
- **QM / SIL compliance** — N/A.

## Post-implementation standards review

- **`coding-standards.md`** — N/A. No code changes.
- **`service-design.md`** — N/A. No service surface changes.
- **`release-and-hygiene.md`** — verify that `CONTRIBUTING.md` still
  parses and renders sensibly under `mdformat` (treefmt) and that
  the lefthook pre-commit pipeline accepts the diff. The file is
  required by the project standards and remains intact.
- **`testing-standards.md`** — N/A. No tests touched.
- **`tooling-and-ci.md`** — N/A. No CI surface changes; the new
  prose rules are convention-only and the CI-enforcement table in
  CONTRIBUTING.md is left as-is.

## Pipeline

1. Branch from latest `main` (already on `aidanns/contributing-md-commit-rationale`).
2. Edit `CONTRIBUTING.md` "Writing release-worthy commits":
   - Insert the cross-reference to
     `.claude/instructions/commit-messages.md` early in the section.
   - Add the five new rule subsections in the natural reading order
     (Subject section first if the rule is title-shaped; Body
     section if it's body-shaped). Causal ordering, brevity, bullet
     threshold, arrows-vs-prose go under the body rules; the
     shouty-marker rule goes wherever the existing backticks
     discussion lives — read the file to decide.
   - Append the 8859338 worked counter-example after the existing
     `7ab4c6a` one (same heading shape).
3. Self-review the diff against the rules being introduced (no
   diff-recap in the new prose, lead with observable behaviour).
4. Commit with `git commit -s`, push, open PR with
   `--label "no changelog"` (chore — not user-visible).
5. Self-review pass on `git diff main...HEAD`, emit
   `READY_FOR_REVIEW` heartbeat, await orchestrator dispatch.
