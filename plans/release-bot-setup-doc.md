<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# release-bot — author the missing per-App setup doc

Closes #380. Adds `docs/release/release-bot-setup.md` so the
release-bot has a sibling per-App setup document equivalent to
`changelog-bot-setup.md` and `merge-bot-setup.md`, and re-points
the existing forward-pointing references at it.

## Context

The repo runs three GitHub Apps for release automation; two have
per-App setup docs and the third does not:

- `docs/release/changelog-bot-setup.md` — present.
- `docs/release/merge-bot-setup.md` — present.
- `docs/release/release-bot-setup.md` — **missing**.

PR #342's commit message currently carries the canonical setup
content; PR #366 (#351) wired a third workflow
(`release-publish.yml`) to the same App, and PRs #368 (#352) and
#369 (#353) committed forward-pointing references to a doc that
does not yet exist:

- `release-pr.yml` and `release-tag.yml` emit
  `::notice::See docs/release/release-bot-setup.md for setup instructions.`
  in their secrets-not-set guard.
- `bots-overview.md` table column links to a stub paragraph that
  marks the doc as pending.

The `CONTRIBUTING.md` § "Release App setup" entry is the interim
authoritative source — but it does not cover Section 1 (what the
bot does), Section 4 (bypass-actor cross-link), or Section 5
(verification recipe), and it predates `release-publish.yml` being
wired to the same App in PR #366.

## Sources

The plan author will cross-reference each of these before drafting
the new doc:

- **PR #342 commit message** (`fd13fb9` on `main`) — canonical
  setup steps the issue body points at.
- **`docs/release/changelog-bot-setup.md`** and
  **`docs/release/merge-bot-setup.md`** — sibling structure /
  heading style / depth to mirror.
- **`docs/release/bots-overview.md`** — "Bypass-actor policy"
  section to cross-link from Section 4 instead of duplicating the
  rationale.
- **`design/decisions/0026-semantic-release-autorelease.md`** — the
  release App identity rationale the issue body cites.
- **`CONTRIBUTING.md` § "Release App setup"** (lines 902–943) —
  current interim source of truth; new doc supersedes the parts
  that overlap, but `CONTRIBUTING.md` keeps the section as a
  cross-link entry (downstream `CONTRIBUTING.md` editing is out of
  scope for this PR; the existing section will continue to work as
  a forward link).
- **`.github/workflows/release-pr.yml` /
  `.github/workflows/release-tag.yml` /
  `.github/workflows/release-publish.yml`** — to confirm the App
  slug, secret names, the three workflow consumers, and the
  permissions the App actually needs at runtime.

## Section-by-section outline

The new `docs/release/release-bot-setup.md` will follow the issue
body's six-section contract, mirroring the heading-style /
heading-level conventions of the two sibling docs:

1. **What the bot does.** Names the three workflow consumers
   (`release-pr.yml`, `release-tag.yml`, `release-publish.yml`),
   explains that `actions/create-github-app-token` mints a
   short-lived installation token per run, and notes that the
   actor login on those workflow events is
   `agent-auth-release-bot[bot]` (per ADR 0026). For each workflow
   covers a one-line summary of what the App token is used for:
   - `release-pr.yml`: opens / refreshes the `release/X.Y.Z` PR
     and pushes the release branch.
   - `release-tag.yml`: pushes the `vX.Y.Z` tag so downstream
     `on: push: tags:` workflows fire (default `GITHUB_TOKEN` tag
     pushes do not).
   - `release-publish.yml`: uploads release assets via
     `gh release upload` so the audit-trail actor matches the rest
     of the release pipeline.
2. **One-time registration.** App slug `agent-auth-release-bot`,
   App name and homepage URL, webhook off (no events handled).
   Repository permissions (Contents: Read & write, Pull requests:
   Read & write, Metadata: Read-only). Install on
   `aidanns/agent-auth` only — not *All repositories*. Mirrors the
   merge-bot doc's Step 1 layout.
3. **Required secrets.** `RELEASE_BOT_APP_ID` and
   `RELEASE_BOT_PRIVATE_KEY`, with the same "full contents
   including BEGIN/END markers and trailing newline" guidance as
   the merge-bot doc. Workflow references called out so a future
   rename does not silently break the bot.
4. **Bypass-actor policy.** One paragraph stating release-bot
   pushes to `release/*` branches and tags only and therefore does
   not need `main`-ruleset bypass; cross-link to
   [`bots-overview.md` § "Bypass-actor
   policy"](bots-overview.md#bypass-actor-policy) for the
   cross-cutting rationale rather than duplicating it. The issue
   body is explicit about cross-linking, not duplicating.
5. **Verifying the install.** Smoke test — open and merge a PR
   with a release-bumping prefix; confirm `release-pr.yml` opens
   the `release/X.Y.Z` PR with `agent-auth-release-bot[bot]` as
   the actor, `release-tag.yml` pushes the tag on its merge, and
   `release-publish.yml` uploads release assets attributed to the
   same App. Same shape as merge-bot's "Verifying the bot
   end-to-end".
6. **Decommissioning.** Key rotation (generate new key, update
   secret, revoke old key) and full decommission (uninstall App,
   delete secrets, the workflows fall back to skipping when the
   secrets-check guard sees both unset). Same shape as the
   sibling docs' rotation / decommissioning sections.

## Cross-reference edits

- **`docs/release/bots-overview.md`** — three changes:
  1. The at-a-glance table row for `agent-auth-release-bot[bot]`:
     replace the "See [Release App setup](../../CONTRIBUTING.md#release-app-setup)"
     link target with `release-bot-setup.md#one-time-registration`
     (or the equivalent anchor) so the column is a per-App link
     like the other two rows.
  2. The "release-bot setup is pending" paragraph that follows
     the table — remove it; the new doc has landed.
  3. The bring-up checklist's step-1 sub-bullet that points at
     `CONTRIBUTING.md` § "Release App setup" — re-point at the
     new doc.
  4. The "Per-App docs are authoritative" footer — replace the
     interim `CONTRIBUTING.md` link with `release-bot-setup.md`.
     Also: also update `release-pr.yml` and `release-tag.yml` are now
     accurately pointing at a real doc (no edit needed in those
     files; they already have the correct path).
- **`docs/release/changelog-bot-setup.md`** — already contains a
  passing reference to release-bot via
  `[agent-auth-release-bot](../../CONTRIBUTING.md#release-app-setup)`.
  Per the issue's acceptance ("only if they currently mention the
  release-bot in passing"), update this link to point at the new
  doc instead of the `CONTRIBUTING.md` interim section.
- **`docs/release/merge-bot-setup.md`** — does **not** mention
  release-bot in passing (the only "release" reference is to the
  decommissioned `semantic-release-agent-auth` App's bypass-actor
  cleanup). Per the issue's acceptance, leave it alone.

## `::notice::` rewording in `release-pr.yml` / `release-tag.yml`

The issue body lists this under "Out of scope" as a mechanical
follow-up. The notice strings already point at the new doc path
(`docs/release/release-bot-setup.md`) — they were written that way
in PR #368 specifically as forward pointers to the doc this PR
adds. **No edit needed** to those workflow files; this PR landing
turns the forward pointers into accurate links automatically.
This is the truly-trivial bundling case the issue body permits;
since the bundling is in fact a no-op (zero edits to the workflow
files), there is nothing to bundle. Default to leaving them alone
remains the right call.

## Verification

Before opening the PR:

- `mdformat docs/release/release-bot-setup.md docs/release/bots-overview.md docs/release/changelog-bot-setup.md`
  reports clean.
- `treefmt` reports clean (whatever Markdown formatter the project
  has wired up — `task fmt` or `treefmt` directly).
- All Markdown links from the new doc and from the changed
  sections of `bots-overview.md` resolve to existing files /
  anchors. Manually walk:
  - `bots-overview.md` § "Bypass-actor policy" anchor.
  - `release-bot-setup.md` workflow file links.
  - `release-bot-setup.md` ADR 0026 link.
  - `bots-overview.md` updated row + bring-up checklist link.
- Diff `git diff main...HEAD` reads as a sibling doc to
  `merge-bot-setup.md` — same heading levels, same code-block
  conventions, same SPDX header.

## Skipped plan-template steps

The standard `plan-template.md` checklist is largely
non-applicable for a docs-only PR. Explicitly skipped:

- **Verify implementation against design doc** — N/A, no code
  behaviour change; the doc *is* the artifact.
- **Threat model** — N/A, no security-relevant code change. ADR
  0026 already covers the release-App identity threat model.
- **Post-incident review (PIR)** — N/A, no vulnerability
  remediation.
- **ADRs** — N/A, ADR 0026 already covers the release App
  identity rationale; the issue body explicitly puts ADR work out
  of scope.
- **Cybersecurity standard compliance / QM-SIL** — N/A for a
  docs-only PR.
- **Coding standards / service design / testing standards** —
  N/A, no code touched.
- **Release and hygiene standards** — partially applicable
  (project files exist; `no changelog` label applies to
  docs-only). Will apply.
- **Tooling and CI standards** — applicable: `mdformat` /
  `treefmt` clean is part of the verification step.

## Out of scope (per issue body)

- Changing release-bot permissions or workflow logic.
- Re-pointing the `::notice::` strings (already correct, see
  above).
- ADR work.

## Acceptance

- `docs/release/release-bot-setup.md` exists with sections 1–6.
- `bots-overview.md` table + bring-up checklist + footer link to
  the new doc; the "pending" paragraph is removed.
- `changelog-bot-setup.md`'s passing release-bot reference points
  at the new doc.
- `merge-bot-setup.md` is left alone.
- `mdformat` / `treefmt` clean.
