<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Commit-message Authoring Rules

Prose conventions for PR titles and COMMIT_MSG bodies. They apply
to every PR — chore commits enter git log too. The structural rules
(prefix allowlist, block shape, trailer parsing) live in
CONTRIBUTING.md and ADR 0037; this file covers the prose inside.

## Bullets

- **Use bullets only for parallel sets of 2+ identical-shape items.**
  A bulleted list is a claim that the items are the same kind of
  thing (configs, error codes, rejected alternatives). One-off
  observations stay in prose.
- **Never bullet a diff recap.** If the bullets read as "renamed X,
  adjusted Y, added Z", the commit body is replaying git show —
  collapse to one sentence on *why*.
- **Trigger phrases.** "Side effects in the same PR", "Also:",
  "while we're here" in the draft mean the PR is doing too much,
  not that bullets will rescue it. Split the PR.

## Backticks

- **Drop them in body prose.** Backticks add visual noise; reserve
  them for the cases below.
- **Self-identifying tokens stay bare.** Filenames with extensions,
  dotted module paths, underscored identifiers, and kebab-case
  identifiers in identifier-shaped contexts are unambiguously code
  to the reader without backticks.
- **Reword ambiguous bare words.** "case statement" not bare `case`;
  "the gpg command" not bare `gpg` when the sentence reads as
  English. Pick the noun phrase, drop the backticks.
- **Double-quote literals with spaces or that read as English.**
  "no changelog", "skipped", "needs-info" — quotes mark the boundary
  that backticks would, and read naturally in git log.
- **Shouty-cased markers strip wrapper syntax.** Write NO_CHANGELOG,
  not ==NO_CHANGELOG==; the wrapper is implementation detail and
  the SHOUTY case already signals "literal token".

## Brevity

- **Default to cutting.** A shorter body that survives a six-month
  re-read beats a longer one that recapitulates the diff.
- **Drop "behaviour at X is unchanged" sentences.** Absence of
  behaviour change is the default reading; calling it out adds
  words without information.
- **KEEP** — exact error strings (greppable from git log --grep),
  non-obvious correctness claims, non-obvious failure modes,
  rejected alternatives.
- **CUT** — re-statements of the diff, narrative connectives that
  carry no claim ("First we …, then we …"), success-path
  confirmations ("the build passes", "tests added").

## Causal narrative ordering

- **Lead with the observable behaviour the reader could have seen.**
  The symptom, the failure, the surprising output — whatever a
  future bisector would paste into git log --grep.
- **Fold setup INTO mechanism, not before.** Introduce shared
  context at the point it earns its keep, not as a preamble.
- **Anti-pattern.** Opening with "X and Y share Z" before the
  reader knows why Z matters forces them to hold context they
  cannot yet evaluate. Reorder so the consequence comes first.

## Arrows vs prose

- **Arrows (`->`) for mechanical sub-steps.** A short pipeline reads
  cleanly as `query before POST -> no snapshot -> sticky comment`:
  each hop is a deterministic consequence of the prior.
- **Prose with explicit connectives for the primary causal claim.**
  Use "so", "because", "which" when the link is a *reasoning* step
  rather than a mechanical one. Arrows hide the reasoning; prose
  exposes it.

## Trailers

When Claude authors the PR, the COMMIT_MSG block must include, in
this order, immediately above the Signed-off-by: trailer:

- A Closes: trailer linking the issue, in the canonical colon form
  `Closes: #N`. Never the bare `Closes #N` — the validator rejects
  it (since #566). The colon form keeps the trailer block uniform
  and is the only shape any agent-authored PR should ever produce.
- A Co-Authored-By: trailer in the form
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`,
  with the model+context string set to whatever the authoring agent
  is actually running as. The literal noreply@anthropic.com email
  renders the Claude icon next to the co-author chip on GitHub.

The two trailers stack contiguously with Signed-off-by: — no blank
lines between them — or `git interpret-trailers --parse` drops them
out of the trailer set and the merge bot loses the issue link and
the co-author attribution.

______________________________________________________________________

See CONTRIBUTING.md -> "Writing release-worthy commits" for the
human-facing rationale and worked counter-examples.
