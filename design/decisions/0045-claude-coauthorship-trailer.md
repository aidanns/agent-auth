<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# ADR 0045 — `Co-Authored-By: Claude` trailer in `==COMMIT_MSG==` blocks

## Status

Accepted — 2026-05-02.

Builds on
[ADR 0037](0037-palantir-commit-prefixes-and-commit-msg-block.md)
(the `==COMMIT_MSG==` block as the squash-merge body authoring
surface) and
[ADR 0038](0038-merge-bot-via-github-app.md) (the merge bot pastes
that block verbatim and authors no commits — the "merge-bot is a
paster" property).
[#553](https://github.com/aidanns/agent-auth/issues/553) is the
tracking issue.

## Context

Claude authors the substance of nearly every PR on this repo —
including the `==COMMIT_MSG==` block that becomes the squash-merge
commit body on `main`. On the feature branch that signal is visible
on individual commits (Claude Code records co-authorship on each
commit it writes), but the squash-merge collapses every branch
commit into one, and only the `==COMMIT_MSG==` block survives into
`git log` and the GitHub UI. As a result the on-`main` history
silently loses the AI-co-authorship signal that the working branch
carried.

That gap matters for three reasons, in priority order:

1. **Audit-trail provenance.** When a future bisect or incident
   review walks back through `git log` on `main`, "was this code
   AI-generated, and by which model?" should be a one-glance
   answer. The current rendering — Aidan as sole author on every
   squash commit — overstates human authorship and hides the model
   identity that drove the change.
2. **Anthropic-convention format.** Anthropic's own tooling
   (Claude Code's auto-generated commit footers) emits a
   `Co-Authored-By: Claude <model+context> <noreply@anthropic.com>`
   trailer. Matching that format keeps the project's audit trail
   compatible with whatever downstream tooling Anthropic ships
   against this convention.
3. **GitHub UI rendering.** The literal Anthropic noreply
   (`noreply@anthropic.com`) renders the Claude icon next to the
   co-author chip in the GitHub commit / PR UI, surfacing the
   provenance signal at exactly the surface a human reviewer
   already looks at.

The `==COMMIT_MSG==` block is the only structured authoring surface
that survives the squash, so the trailer has to land inside it. ADR
0037 already defined the block as the canonical body authoring
surface; ADR 0038 already defined the merge bot as a strict paster
that authors no commits. The decision is therefore just: who adds
the trailer, and how is the rule enforced?

## Considered alternatives

### Server-side merge-bot injection

Teach `merge-bot.yml` (or `extract-commit-msg-block.py`) to
inject the trailer into the `==COMMIT_MSG==` body server-side,
just before the bot calls `PUT /pulls/{n}/merge`. The bot would
detect Claude-authored PRs (e.g. by author allowlist) and splice
the trailer in between the existing `Closes:` and
`Signed-off-by:` lines.

**Rejected** because:

- Relaxes ADR 0038's "merge-bot is a paster" property — the bot
  starts authoring commit-body content, which then has to be
  audited against the same rigour as a human author. Today the
  bot is trivially auditable (it pastes whatever was already in
  the PR body); a transforming bot is not.
- Bot-author exemption logic adds complexity. The bot would have
  to maintain a list of "PR authors that are bots" (release-bot,
  changelog-bot, dependabot adaptor) and skip injection for them,
  inverting the natural fall-out described below.
- Break-glass `gh pr merge --admin --squash` paths would still
  drop the trailer, since they bypass the bot entirely.
- A change to `merge-bot.yml` requires ruleset bypass-actor
  re-validation; doc-only conventions do not.

### Bare `Co-Authored-By: Claude` (no model identity)

Drop the model + context-window string and emit just
`Co-Authored-By: Claude <noreply@anthropic.com>`.

**Rejected** because:

- The audit goal (1 above) wants model-version bisect signal. A
  hypothetical `Opus 4.6 → 4.7` regression in code quality on a
  specific commit class is much easier to spot when the trailer
  enumerates the model that wrote each commit.
- The writing agent reliably knows its own model identity (it's in
  the system prompt header), so collecting the data is free at
  write-time. Discarding it would be a deliberate audit-grade
  downgrade with no offsetting benefit.

### `claude[bot]` GitHub-account email

Use a `claude[bot]@users.noreply.github.com`-shape email so the
co-author chip links to a GitHub account.

**Rejected** because:

- The literal Anthropic noreply (`noreply@anthropic.com`) already
  renders the Claude icon in the GitHub UI (verified empirically
  on existing co-authored commits), preserving point (3) above
  without sacrificing point (2).
- A `claude[bot]` account is not Anthropic-canonical — picking a
  custom GitHub account name would commit the project to whatever
  that account turns out to be over time.

### Multi-trailer audit form (Anthropic noreply *and* `claude[bot]`)

Emit two co-author trailers — one with the Anthropic noreply (for
the model-identity audit signal) and one with the `claude[bot]`
account (for richer GitHub UI rendering).

**Rejected** because:

- GitHub renders both trailers as co-authors, so the contributor
  graph would gain a duplicate entry per Claude-authored commit.
  That bloats the contributor list and over-counts AI involvement
  on the repo's headline contributor stats.
- The single Anthropic-noreply trailer already gets both the icon
  rendering and the audit identity; the multi-trailer form adds
  cost with no offsetting benefit.

### Per-PR `==MODEL==` marker read by merge-bot

Add a structured `==MODEL==` … `==MODEL==` block to the PR template
that the merge bot reads at merge time and folds into the body as
a `Co-Authored-By:` trailer. Decouples the marker from the trailer
shape so a future evolution of the trailer convention is a one-place
change.

**Deferred — not rejected.** Useful only if model identity ever
becomes load-bearing for an automated bisect tool that wants
structured access to the model string without parsing the trailer
free-form. Today there is no such tool. YAGNI for v1; revisit if
the audit signal grows from "human glance at `git log`" to
"automated regression-by-model dashboard".

## Decision

The author of the `==COMMIT_MSG==` block is responsible for the
`Co-Authored-By: Claude` trailer. For Claude (the overwhelmingly
typical author) the rule is enforced via documentation read at
PR-write time: the PR template comment block, CONTRIBUTING.md
("Writing PRs" → "Claude attribution trailer"), and a one-line
index entry in the project CLAUDE.md.

Trailer format:

```
Co-Authored-By: Claude <model+context> <noreply@anthropic.com>
```

The model + context-window string is whatever the writing agent is
actually running as (e.g. `Claude Opus 4.7 (1M context)`).

Position: between `Closes:` and `Signed-off-by:` inside the
contiguous trailer block, e.g.

```
Closes: #N
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
```

Bot-authored PRs (`agent-auth-release-bot[bot]`,
`changelog-bot[bot]`, the `dependabot-adaptor`-synthesised
Dependabot blocks) are exempted by natural fall-out — their
`==COMMIT_MSG==` blocks are rendered deterministically from YAML
by Python helpers, with no Claude in the loop. No filter logic is
required to skip them, because the rule applies to authors and
those PRs have no Claude author to read it.

The convention applies forward-only from the merge of this ADR's
PR. No retroactive backfill of historical squash commits on `main`.

No validator change in v1 — the four edge cases covered in
CONTRIBUTING.md ("Claude attribution trailer") are sufficiently
nuanced that a regex shape-check would either miss legitimate
omissions (bot PRs, hand-authored-by-human-only PRs) or reject
legitimate variants (e.g. as model names evolve, the
`<model+context>` string shape drifts). The cost of a malformed or
missing trailer is low (it doesn't break any pipeline, just
under-records provenance), and the maintenance friction of a
shape-checker would compound every time a model name changes.

## Consequences

**Positive**

- Every Claude-authored squash commit on `main` carries provenance
  discoverable via `git log` and the GitHub UI. A future bisecting
  reader (or model-regression hunter) sees the model identity
  inline.
- ADR 0038's "merge-bot is a paster" property is fully preserved.
  The bot continues to author no commit-body content; the trailer
  rides in on whatever the PR author wrote.
- No new validator gate, no merge-bot transform, no per-PR
  template field. The change is text-only — three doc surfaces
  (PR template comment, CONTRIBUTING.md, CLAUDE.md index entry)
  plus this ADR.
- Bot-PR exemption is free. The convention applies to authors;
  bot-authored PRs simply have no Claude author to read the rule,
  so they naturally render no trailer.

**Negative / trade-offs**

- Audit completeness depends on Claude (or a human author) reliably
  reading the rule at write-time. Mitigated by layering instruction
  surfaces for salience: the PR template comment is right next to
  the `==COMMIT_MSG==` block (highest write-time visibility),
  CONTRIBUTING.md is the canonical reference (with the format and
  the four edge cases), and CLAUDE.md carries a one-line index
  entry so an agent loading the project context discovers the rule
  via the same path it discovers every other commit-body
  convention.
- The model identity in the trailer drifts when models change.
  Accepted: the trailer isn't a verifiable cryptographic assertion,
  it's a self-attestation. "Roughly which model was active when
  this code was generated" is good enough for the audit goal.
- `gh pr merge --admin --squash` break-glass merges depend on the
  human committer remembering to paste the trailer manually. The
  CONTRIBUTING.md edge-case bullet calls this out so the rule is at
  least documented at the surface a maintainer would consult before
  doing a break-glass merge.

**Out of scope (called out so a future reader doesn't ADR-hunt)**

- No retroactive backfill of historical squash commits on `main`.
  Rewriting history to add the trailer would invalidate every
  existing commit signature and diverge from the published tag
  hashes. The provenance gap on pre-ADR commits is accepted as
  history.
- No validator change in v1, per the *Decision* section's
  shape-check rationale.

## Follow-ups

None tracked as separate issues. The deferred `==MODEL==` marker
(Considered alternatives §5) is implicit: if a future automated
tool needs structured model access, file an issue then.

<!-- REUSE-IgnoreEnd -->
