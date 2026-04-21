<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Adopt OWASP ASVS as application security verification standard

Issue: [#112](https://github.com/aidanns/agent-auth/issues/112).

Source standard: `.claude/instructions/design.md` — *Cybersecurity
standard* (complements the existing NIST SP 800-53 selection in
`SECURITY.md` at the application layer, and pairs with NIST SSDF
adopted in ADR 0015).

## Goal

Record OWASP ASVS v5 as the project's application-security
verification standard and produce a per-chapter conformance audit so
future plans can walk ASVS evidence for their surface area in the
same way they walk NIST SP 800-53 controls today.

1. Add `design/ASVS.md` walking ASVS v5 chapters, naming L2 as the
   target level, and recording per-chapter conformance (Implemented
   / Partial / Planned / Not applicable) with references to the
   existing artefact (ADR, threat-model row, source file, issue)
   that satisfies or tracks the concern.
2. Name ASVS in `SECURITY.md` under a new
   `## Application security standard` section, mirroring the
   existing `## Cybersecurity standard` and `## SDLC standard`
   sections.
3. Backfill ADR 0019 explaining why ASVS is the right
   application-layer companion to the existing
   system-controls / SDLC / supply-chain standards.
4. Update ADR 0015 and `design/SSDF.md` ASVS references to point
   at the new `design/ASVS.md` now that #112 is resolved.
5. File follow-up issues for every ASVS chapter the audit
   classifies as `Partial` or `Planned` and that is not already
   tracked by an existing GitHub issue.

## Non-goals

- Implementing any new application-layer control. The audit
  records current state; gaps are tracked as follow-ups, not
  closed.
- Retroactively refactoring existing controls to match ASVS
  verbatim wording. Where an existing mitigation discharges an
  ASVS concern by equivalent means, that is recorded as
  Implemented with a rationale.
- Walking every individual ASVS control number. ASVS v5 has
  hundreds of verification requirements; the audit records
  conformance at chapter / section granularity, matching how
  `design/SSDF.md` records SSDF at practice-task granularity.
- Targeting ASVS L3. L3 assumes high-assurance / regulated
  contexts (finance, healthcare) that do not apply to a
  solo-maintained, local-only, single-user auth project.

## Deliverables

1. **`design/ASVS.md`** — opens with a short rationale paragraph
   (why ASVS, why L2, how it pairs with NIST SP 800-53 / SSDF /
   supply-chain standards) and a per-chapter conformance table.
   Table columns: *Chapter*, *Summary*, *Scope*, *Conformance*,
   *Evidence / gap*. Rows follow ASVS v5's chapter numbering (V1
   … V17). Each Partial / Planned row cites the tracking issue;
   each Implemented row cites an ADR, `SECURITY.md` threat-model
   row, source file, or design-doc section. Chapters scoped out
   of the project (no web frontend, no OAuth/OIDC flows, no
   WebRTC, no user file uploads) are listed with an explicit
   "Not applicable" rationale.
2. **`SECURITY.md` — new `## Application security standard`
   section** placed between the existing `## SDLC standard` and
   `## Supply-chain artifacts` sections. One paragraph naming
   ASVS v5 (target L2) and linking `design/ASVS.md`; one bullet
   list naming the in-scope chapters and why the out-of-scope
   chapters are excluded; one sentence recording the relationship
   with the companion standards.
3. **`design/decisions/0019-owasp-asvs-application-security-standard.md`**
   — ADR backfilling the decision. Status
   `Accepted — 2026-04-21`. Context captures the
   system-controls / SDLC / application-controls / build-provenance
   split. Considered alternatives covers (a) PCI-DSS (rejected —
   industry-specific to cardholder data), (b) OWASP MASVS
   (rejected — mobile-app scope, not relevant to an HTTP auth
   service), (c) CWE Top 25 / SANS lists (rejected — weakness
   catalogue, not a verification standard), (d) relying on
   NIST SP 800-53 alone (rejected — leaves the application
   surface without a checklist that can be walked per-plan).
   Decision names ASVS v5 at target L2. Consequences note the
   pairing with ADR 0015 (SSDF) and the per-plan ASVS walk that
   now becomes possible.
4. **`design/decisions/0015-nist-ssdf-sdlc-standard.md`** —
   update the ASVS `Follow-ups` line to point at ADR 0019 /
   `design/ASVS.md` instead of #112.
5. **`design/SSDF.md`** — update the header ASVS reference from
   `tracked in #112` to a direct link to `design/ASVS.md`, so
   the SDLC standard cross-references the application standard
   instead of the resolved issue.
6. **`design/decisions/README.md`** — adds entry linking ADR
   0019\.
7. **`scripts/verify-standards.sh`** — adds a new
   `application-security-standard` entry to `security_sections`,
   enforcing that `SECURITY.md` contains a heading matching
   `## Application security standard`. Regression-checkable
   mirror of the existing `cybersecurity-standard` and
   `sdlc-standard` gates.
8. **`CHANGELOG.md`** — `Unreleased` entry noting the ASVS
   adoption, the new gate, and the cross-references updated in
   SSDF / ADR 0015.
9. **GitHub follow-up issues** — one per Partial / Planned
   chapter that is not already tracked. Cross-link #112 as the
   originating audit.

## Approach

**Draft `design/ASVS.md` first.** Walk ASVS v5 chapter-by-chapter.
For each chapter, record current state from:

- existing ADRs (`design/decisions/0006`–`0018`),
- `SECURITY.md` threat model, key handling, revocation, and
  audit-surface sections,
- `design/DESIGN.md` for observability and API surface,
- source under `src/agent_auth/` and `src/things_bridge/` for
  request validation, scope enforcement, token handling, and
  field encryption,
- existing open issues (#6 plugin boundary, #101 TLS between
  devcontainer and host, #102 rate limiting, #103 audit
  chaining, #109 / #110 / #111 supply chain).

Each chapter lands in one of four conformance buckets:

- **Implemented** — existing artefact satisfies the chapter's
  L2 concerns.
- **Partial** — partial coverage with a known gap; cite the
  issue tracking the remainder.
- **Planned** — chapter selected but not yet started; cite the
  issue.
- **Not applicable** — chapter's subject is absent from the
  project (e.g. V3 Web Frontend Security — no browser-facing UI;
  V10 OAuth and OIDC — custom token scheme is not OAuth;
  V17 WebRTC — no WebRTC). Record the rationale in-line so
  `plan-template.md` walkers can see why the chapter was
  skipped.

**Update `SECURITY.md` second.** Add the
`## Application security standard` section. Keep it short —
details live in `design/ASVS.md`. The section's existence is
gated by `verify-standards.sh`; its content is not.

**Write ADR 0019 third.** Follow `design/decisions/TEMPLATE.md`
exactly. Keep the ADR under one page of prose.

**Update ADR 0015 and `design/SSDF.md` fourth.** Swap the
`tracked in #112` references for direct links to
`design/ASVS.md` now that the tracked work has landed.

**Wire the gate last.** Extend `security_sections` in
`scripts/verify-standards.sh` with the new
`application-security-standard` entry. Run `task verify-standards`
locally for a green baseline, then temporarily strip the new
`## Application security standard` heading and confirm the gate
reports the exact missing section.

**File follow-ups at the end.** After `design/ASVS.md` is
complete, grep its *Partial* / *Planned* rows and create a
GitHub issue for each one that is not already covered by an
existing open issue. Link each new issue back to #112 and to the
`design/ASVS.md` row anchor.

## Design and verification

- **Verify implementation against design doc** — `design/ASVS.md`
  is the design doc for application-security conformance.
  Cross-check each row against the cited ADR / source / workflow;
  if the cited artefact does not implement the chapter's concern,
  downgrade Implemented → Partial / Planned and file the gap.
- **Threat model** — no new security-relevant runtime behaviour.
  `SECURITY.md`'s STRIDE tables are not modified. Skip.
- **Architecture Decision Records** — ADR 0019 *is* the design
  decision for this change. No other decisions fall out.
- **Cybersecurity standard compliance** — this change records
  the application-surface standard that pairs with NIST SP 800-53
  and NIST SSDF. Walk NIST SP 800-53's AC (Access Control), IA
  (Identification and Authentication), SC (System and
  Communications Protection), and SI (System and Information
  Integrity) families against the new ASVS audit to confirm the
  two agree; if any 800-53 control is stricter than the
  equivalent ASVS concern (or vice versa), note the delta in
  `design/ASVS.md`.
- **Verify QM / SIL compliance** — no change to the QM
  declaration. ASVS conformance is additive to ASSURANCE.md's
  Required-activities list; ASSURANCE.md itself is not modified.

## Post-implementation standards review

- **Coding standards** — docs + one shell-script gate. Verify
  the new `security_sections` entry uses the same `name|pattern`
  shape as its neighbours and stays inside the `keep-sorted`
  block.
- **Service design standards** — docs only. Skip.
- **Release and hygiene** — add a `CHANGELOG.md` `Unreleased`
  entry noting the ASVS adoption and the new gate. No versioning
  impact; no pinned-schema changes.
- **Testing standards** — no test files touched. The new gate is
  exercised by the existing `task verify-standards` CI job.
- **Tooling and CI standards** — gate runs under the existing
  `task verify-standards` target; no new tool added.

## Follow-ups

- Per-chapter gap issues filed during the audit, linked from the
  relevant rows of `design/ASVS.md` and cross-referenced to
  [#112](https://github.com/aidanns/agent-auth/issues/112).
