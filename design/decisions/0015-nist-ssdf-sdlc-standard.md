<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0015 — Adopt NIST SSDF (SP 800-218) as the SDLC standard

## Status

Accepted — 2026-04-20.

Backfilled ADR. Pairs with ADR 0006–0013 (system-level decisions
already covered in `SECURITY.md`'s NIST SP 800-53 selection). Links
to [#113](https://github.com/aidanns/agent-auth/issues/113).

## Context

`SECURITY.md` already records **NIST SP 800-53 Rev 5** as the
project's cybersecurity standard — covering what the *running*
agent-auth system does (access control, audit, authentication,
etc.). That leaves two gaps visible to any downstream consumer
who wants to reason about the project's security posture:

1. **SDLC-side practices.** How the project is built, reviewed,
   tested, released, and patched. NIST SP 800-53 touches SA
   (System and Services Acquisition) at a high level, but it is
   not structured as a per-task checklist a solo-maintained
   project can walk before each PR.
2. **Application-layer verification.** What the auth surface
   itself guarantees about input validation, session management,
   token handling, etc. — resolved separately by
   [ADR 0019](0019-owasp-asvs-application-security-standard.md)
   (OWASP ASVS v5 at L2), tracked originally in
   [#112](https://github.com/aidanns/agent-auth/issues/112).

This ADR resolves gap (1) by naming an SDLC-practice standard.
The forces in play:

- `.claude/instructions/plan-template.md` already requires a
  *Cybersecurity standard compliance* walk for every PR. Without
  an SDLC-side standard, that walk has no content for
  build/release/response concerns, so they drift.
- Executive Order 14028 and OMB M-22-18 anchor on SSDF. Picking
  SSDF aligns the project's vocabulary with what a future larger
  downstream consumer would already understand.
- Solo-maintainer scale rules out frameworks that presuppose
  team-level governance or multi-role certification.

## Considered alternatives

### BSIMM (Building Security In Maturity Model)

Descriptive framework derived from anonymised surveys of
industrial software security programmes.

**Rejected** because:

- Descriptive, not prescriptive — organisations measure where
  they sit on the BSIMM curve, but there is no public per-task
  checklist a PR can be verified against.
- Geared to multi-team organisations with dedicated security
  staff; the activity catalogue assumes roles that don't exist
  at solo-maintainer scale.

### OWASP SAMM (Software Assurance Maturity Model)

Open prescriptive framework, roughly comparable in scope to
SSDF.

**Rejected** because:

- Overlaps SSDF on the practices this project cares about without
  adding per-task rigour in the areas SSDF is already stronger
  (vulnerability response, provenance).
- SSDF has become the lingua franca of US federal SDLC
  attestation; adopting SAMM would require a second mapping to
  SSDF whenever a consumer asks for SSDF evidence.

### Name no SDLC-side standard

Leave the SDLC side implicit; rely on `design/ASSURANCE.md`
(QM-level ISO 9000 practices) and `.claude/instructions/*.md`.

**Rejected** because:

- Leaves the per-PR standards walk in `plan-template.md` with
  no structured SDLC content to walk against.
- Makes it harder to file and track gaps uniformly: each SDLC
  concern (SAST, SBOM, provenance, vulnerability response)
  would need its own ad-hoc classification.

## Decision

Adopt **NIST SP 800-218 v1.1 — Secure Software Development
Framework (SSDF)** as the project's SDLC-practices standard.

- Per-practice conformance lives in `design/SSDF.md`, structured
  by the four SSDF practice groups (PO, PS, PW, RV).
- `SECURITY.md` grows a short `## SDLC standard` section that
  names SSDF, links `design/SSDF.md`, and cross-references the
  companion standards (SP 800-53 for system controls, ASVS for
  application controls, SLSA / cosign / SBOM for supply chain).
- `scripts/verify-standards.sh` asserts the `## SDLC standard`
  section exists in `SECURITY.md` — the existence of the pointer
  is gated; the content of `design/SSDF.md` is not.
- Per-plan SDLC walks use `design/SSDF.md` alongside the existing
  SP 800-53 control walk. Gaps identified during a plan get
  tracked as GitHub issues linked from the relevant
  `design/SSDF.md` row.

## Consequences

- The per-PR standards walk gains a concrete SDLC checklist. Gaps
  (e.g. SAST coverage, SBOM publication, post-incident reviews)
  now surface against a named practice task rather than being
  tribal knowledge.
- Four related supply-chain issues (#109 SLSA, #110 cosign, #111
  SBOM, #108 OpenSSF Scorecard) now have a standards-level home:
  SSDF PS.2 / PS.3 are the practices they discharge.
- `design/SSDF.md` becomes a living document that future plans
  must update in the same PR as the change, mirroring how
  `SECURITY.md` is refreshed before security-relevant changes
  land.
- SSDF is a practice framework, not a conformance regime — the
  project does not claim SSDF certification, only that it uses
  SSDF to structure its SDLC evidence. No third-party audit is
  implied.
- Adopting SSDF does not change the project's QM-level assurance
  declaration in `design/ASSURANCE.md`. SSDF and ASSURANCE.md
  both enumerate per-change activities; `ASSURANCE.md` is the
  ISO-9000-style *what must ship*, SSDF is the standards-labelled
  *what SDLC practice each of those maps to*.

## Follow-ups

- Per-practice gap issues filed as part of
  [#113](https://github.com/aidanns/agent-auth/issues/113) —
  linked from the relevant rows of `design/SSDF.md`.
- OWASP ASVS companion — resolved by
  [ADR 0019](0019-owasp-asvs-application-security-standard.md)
  (tracked originally in
  [#112](https://github.com/aidanns/agent-auth/issues/112)).
- CNCF TAG-Security self-assessment structure for `SECURITY.md`
  threat model — tracked in
  [#114](https://github.com/aidanns/agent-auth/issues/114).
