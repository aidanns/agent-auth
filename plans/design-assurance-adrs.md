# Plan: ASSURANCE.md + ADR template, index, and backfill

Issues: [#21](https://github.com/aidanns/agent-auth/issues/21),
[#22](https://github.com/aidanns/agent-auth/issues/22).

Source standard: `.claude/instructions/design.md` — *Architecture
Decision Records* and *Quality management / safety integrity level*.

## Goal

Bring the `design/` directory up to the standards defined in
`design.md`:

1. Declare the project's QM level (ISO 9000-style) in
   `design/ASSURANCE.md` with rationale and the required activities,
   documentation, and evidence the implementation plans must verify
   against.
2. Add a committed ADR template and an index `README.md` to
   `design/decisions/`.
3. Backfill ADRs for every significant design decision already made
   that is not yet captured in an ADR (token format, SQLite + field-
   level AES-256-GCM encryption, system keyring for signing / encryption
   keys, CLI/server split, three-tier scope model + JIT approval,
   refresh-token reuse → family revocation, XDG path layout,
   AppleScript-based Things bridge).
4. Wire both into `scripts/verify-standards.sh` so regressions fail
   CI rather than drifting.

## Non-goals

- Refactoring any of the existing ADRs (`0001`–`0005`). They already
  follow the Context / Decision / Consequences shape the template
  codifies; updating them is out of scope.
- Selecting a cybersecurity standard — that's a separate follow-up
  tracked under its own issue.
- Populating `plans/` ADR-template sections beyond this one.
- Introducing SIL-style (IEC 61508) evidence requirements. Per the
  decision captured in `ASSURANCE.md`, agent-auth is not
  safety-critical and adopts a QM-level posture.

## Deliverables

1. **`design/ASSURANCE.md`** — declares QM (ISO 9000-style) as the
   project's assurance level, with rationale, required activities
   (code review, testing, CI gating, audit logging, ADRs for
   significant decisions), required documentation, and required
   evidence (test artefacts, CI runs, ADR index, audit log
   retention). Each implementation plan verifies conformance per
   the existing `plan-template.md` step.
2. **`design/decisions/README.md`** — index listing every ADR by
   number, title, and one-line summary. Links each ADR file. Opens
   with a short paragraph describing the directory's purpose and
   pointing at the template.
3. **`design/decisions/TEMPLATE.md`** — the ADR skeleton. Required
   sections: Status, Context, Decision, Consequences. Optional
   sections (Considered alternatives, Follow-ups) documented inline.
   The template file itself is explicitly excluded from the
   `Context`/`Decision`/`Consequences` gate (it's the skeleton, not
   an ADR).
4. **Eight new ADRs** in `design/decisions/`, numbered `0006` to
   `0013`, each linked from the index:
   - `0006-token-format.md` — `aa_<id>_<sig>` / `rt_<id>_<sig>` with
     prefix-in-signature HMAC-SHA256.
   - `0007-sqlite-field-level-encryption.md` — SQLite at XDG data
     path with AES-256-GCM encryption of sensitive columns only.
   - `0008-system-keyring-for-key-material.md` — signing and
     encryption keys held in macOS Keychain / libsecret, never on
     disk.
   - `0009-cli-server-split.md` — CLI writes + server validates;
     why agent-auth ships as two binaries sharing one process's
     keyring.
   - `0010-three-tier-scope-model.md` — allow / prompt / deny tiers
     and the JIT approval plugin surface.
   - `0011-refresh-token-reuse-family-revocation.md` — single-use
     refresh tokens, reuse triggers family-wide revocation, re-issuance
     path requires JIT approval.
   - `0012-xdg-path-layout.md` — config at `$XDG_CONFIG_HOME`, data
     (tokens.db) at `$XDG_DATA_HOME`, state (audit log) at
     `$XDG_STATE_HOME`.
   - `0013-applescript-things-bridge.md` — why the bridge talks to
     Things 3 via `osascript` despite the in-process plugin caveat,
     and the out-of-process migration boundary it sets up (see
     `src/things_client_common/`).
5. **`scripts/verify-standards.sh`** gains two new gates:
   - **ADR gate** — iterate every file under `design/decisions/`
     whose name is neither `README.md` nor `TEMPLATE.md`, assert each
     contains `## Context`, `## Decision`, and `## Consequences`
     sections (case-insensitive header match anchored to start of
     line), and assert each is linked from `design/decisions/README.md`
     (link target matches the filename).
   - **ASSURANCE gate** — assert `design/ASSURANCE.md` exists and
     contains at least one of `QM` / `SIL` as a declared level plus
     headings for required activities and evidence (`## Required activities`, `## Required evidence`).

`CHANGELOG.md` does not yet exist in the repo; bootstrapping it is
out of scope for this PR and tracked as
[#98](https://github.com/aidanns/agent-auth/issues/98) (see
Follow-ups).

## Approach

**ADR template first.** Write `TEMPLATE.md` with the required
sections, then the index `README.md` with an entry per existing ADR
(`0001`–`0005`) so the gate is green before the new ADRs land.

**Backfill second.** Work through the eight backfills in deliverable
order. Each ADR records the decision as made *today* (present-tense
Status: `Accepted — 2026-04-19`), with a Context paragraph summarising
what prompted the decision (e.g. "threat model required signing key
never touch disk"), the Decision itself (one-paragraph summary), and
Consequences (trade-offs accepted, known gaps, follow-up issues).
Cross-reference `design/DESIGN.md` sections where the decision is
already documented to keep ADRs concise.

**ASSURANCE.md third.** The QM declaration names the required
activities (code review, ADRs for significant decisions, testing
coverage thresholds, CI gating, audit logging, threat model in
`SECURITY.md`), required documentation (DESIGN.md, ADRs, SECURITY.md,
plans for each change), and required evidence (CI runs green, test
artefacts, ADR index complete, audit-log retention). It closes with a
pointer to `.claude/instructions/plan-template.md` "Verify QM / SIL
compliance" as the per-change checkpoint.

**Gates last.** Add the two regression checks to
`scripts/verify-standards.sh`. Run `task verify-standards` locally to
confirm a green baseline; temporarily introduce a violation (strip a
Consequences heading, remove an index entry, rename `ASSURANCE.md`)
and confirm each gate fails with a clear message before reverting.

## Design and verification

- **Verify implementation against design doc** — cross-check each
  backfilled ADR against the corresponding section of `design/DESIGN.md`
  to catch drift. If any ADR records a decision the code no longer
  matches, update the ADR (or the code) before landing.
- **Threat model** — no new security-relevant behaviour introduced;
  `SECURITY.md` is not touched by this change. Skip.
- **Architecture Decision Records** — the change *is* the ADR
  backfill. Each new decision gets its own file.
- **Cybersecurity standard compliance** — selecting the standard is
  an explicit non-goal (tracked separately). Skip.
- **Verify QM / SIL compliance** — the change adds the QM declaration
  itself; conformance check is "does this PR match the declaration".
  Validate by walking the Required-activities list in ASSURANCE.md
  against this PR: ADRs written (yes), tests (not applicable — docs
  only), CI gating (yes — new regression checks), audit logging
  (unaffected).

## Post-implementation standards review

- **Coding standards** — docs only. No code changes beyond
  `scripts/verify-standards.sh`. Verify the new gates use the existing
  `strip_comments` helper and the same `fail_*_check` pattern as the
  neighbouring checks.
- **Service design standards** — docs only. Skip.
- **Release and hygiene** — add CHANGELOG entry. No pinned schema
  changes; no versioning impact.
- **Testing standards** — no test files touched. The new
  `verify-standards.sh` gates are exercised by the existing
  `verify-standards` task, which runs in CI.
- **Tooling and CI standards** — new gates run under `task verify-standards`, already wired into CI via `task check`.

## Follow-ups

- Bootstrap `CHANGELOG.md` at the repo root —
  [#98](https://github.com/aidanns/agent-auth/issues/98).
- Cybersecurity standard selection (ISM / NIST SP 800-53) — separate
  issue.
- If future ADRs start covering decisions that span multiple files,
  consider adding a `supersedes` / `superseded by` cross-reference
  convention (already used informally by ADR 0003 → 0001).
