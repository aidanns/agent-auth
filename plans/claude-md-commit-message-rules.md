<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Commit-message authoring rules for Claude sessions

Issue #561 (parent #560). Add a session-loaded rules file so a fresh
Claude session applies the same prose conventions on its first
commit-message draft.

## Decision recap

- Location: `.claude/instructions/commit-messages.md` (per issue
  Decision 2026-05-03 — option a in the parent meta-tracker).
- `CLAUDE.md` "Detailed instructions" gains a one-line pointer.
- The new file cross-references the human-facing rationale in
  `CONTRIBUTING.md` -> "Writing release-worthy commits". The reverse
  pointer (CONTRIBUTING.md -> instruction file) is a parallel-PR
  scope (#562) — a brief broken-link window is acceptable.

## Five rule clusters (terse phrasing)

Match the prose style of `coding-standards.md` /
`service-design.md`: `**bold-cluster**` lead, single-line directive,
anti-pattern triggers called out where applicable. Sub-bullets only
when the cluster has multiple distinct sub-rules.

1. **Bullets** — only for parallel sets of 2+ identical-shape items;
   never for diff recap. Trigger phrases on draft prose ("Side
   effects in the same PR", "Also:", "while we're here") signal the
   PR is doing too much, not that bullets are needed.
2. **Backticks** — drop in body prose. Self-identifying tokens stay
   bare (filenames with extensions, dotted paths, underscored
   identifiers, kebab-case identifiers in identifier-shaped contexts).
   Reword ambiguous bare words ("case statement" not bare `case`).
   Double-quote literals with spaces or that read as English ("no
   changelog", "skipped"). Shouty-cased markers strip wrapper syntax
   (`==NO_CHANGELOG==` -> NO_CHANGELOG).
3. **Brevity** — default to cutting; explicit KEEP / CUT lists. Drop
   "behaviour at X is unchanged" sentences. KEEP exact error strings
   (greppable), non-obvious correctness claims, non-obvious failure
   modes, rejected alternatives. CUT re-statements, narrative
   connectives, success-path confirmations.
4. **Causal narrative ordering** — lead with the observable
   behaviour the reader could have seen; fold setup INTO mechanism,
   not before. Anti-pattern: opening with "X and Y share Z" before
   the reader knows why Z matters.
5. **Arrows vs prose** — arrows (`->`) for mechanical sub-steps
   ("query before POST -> no snapshot -> sticky comment"); prose
   with explicit connectives ("so", "because", "which") for the
   primary causal claim.

## CLAUDE.md update

Insert one bullet in the "Detailed instructions" list, between the
`coding-standards.md` and `design.md` entries (alphabetical-ish
neighbours; also groups with the other prose-quality conventions).

Phrasing: `commit-messages.md` — bullets, backticks, brevity, causal
ordering, and arrows-vs-prose rules for PR titles and ==COMMIT_MSG==
bodies.

## Cross-reference

In `commit-messages.md`, end with a one-line pointer:
"See CONTRIBUTING.md -> 'Writing release-worthy commits' for the
human-facing rationale and worked counter-examples."

## Skipped plan-template steps (with justification)

- **Threat model / PIR / ADR / cybersecurity / QM-SIL** — none
  apply: docs-only change to a developer-facing instruction file,
  no code, no schema, no security surface, no decision worth ADR
  weight (the file location decision is recorded in the parent
  issue's clarification).
- **Verify implementation against design doc** — no design doc
  governs `.claude/instructions/`; the issue body is the spec.

## Post-implementation standards review

- `coding-standards.md`, `service-design.md`,
  `release-and-hygiene.md`, `testing-standards.md`,
  `tooling-and-ci.md` — all code/service-shaped; not applicable to a
  prose-only edit. Confirm each one is not applicable rather than
  silently skip.
- Apply the rules in the new file to the new file's own prose and
  to the PR's `==COMMIT_MSG==` block before pushing.
