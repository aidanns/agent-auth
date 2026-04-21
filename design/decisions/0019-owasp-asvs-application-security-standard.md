<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0019 — Adopt OWASP ASVS v5 as the application security verification standard

## Status

Accepted — 2026-04-21.

Backfilled ADR. Pairs with
[ADR 0015](0015-nist-ssdf-sdlc-standard.md) (NIST SSDF SDLC
standard) and the NIST SP 800-53 Rev 5 cybersecurity selection
recorded in [`SECURITY.md`](../../SECURITY.md#cybersecurity-standard).
Resolves [#112](https://github.com/aidanns/agent-auth/issues/112).

## Context

`SECURITY.md` records **NIST SP 800-53 Rev 5** as the project's
cybersecurity standard (what the running system must control) and
ADR 0015 records **NIST SSDF (SP 800-218)** as the SDLC-side
practice standard (how the project builds the software). That
still leaves one gap visible to any downstream consumer
reasoning about the project's security posture: the application
surface itself — input validation, session management, token
handling, authorisation enforcement, transport confidentiality,
secure defaults — has no single named standard to grep evidence
against.

`SECURITY.md` threat-model rows already name each mitigation, but
they do not structure the surface as a walkable checklist. Plans
that touch the HTTP surface need an application-standard
counterpart to the NIST SP 800-53 family walk they already do;
otherwise the application-layer concerns get rediscovered
per-plan rather than verified against a shared list.

The forces in play:

- `.claude/instructions/plan-template.md` already mandates a
  *Cybersecurity standard compliance* walk per PR. Without an
  application-surface standard, the walk only exercises the five
  in-scope SP 800-53 families (AC / AU / IA / SC / SI) — which
  leaves application-surface concerns (input validation,
  encoding, configuration hardening, secure logging) under-walked.
- ADR 0015 explicitly deferred the application-layer selection
  to [#112](https://github.com/aidanns/agent-auth/issues/112).
  Every PR landed since then has had to skip that row of the
  plan-template walk.
- Aligning on OWASP ASVS matches the vocabulary a larger
  downstream consumer (auditor, security reviewer, enterprise
  adopter) would already understand. ASVS is the de facto
  standard for application-layer verification, cited by
  PCI-DSS v4, NIST SP 800-53B, and most cloud-provider
  shared-responsibility models.

## Considered alternatives

### PCI-DSS (Payment Card Industry Data Security Standard)

Prescriptive, vertical-specific standard for cardholder data
handling.

**Rejected** because:

- Scoped to cardholder data. agent-auth does not store, process,
  or transmit cardholder data; the standard's most valuable
  controls (tokenisation of PANs, cryptographic key management
  for card data) do not apply.
- Where PCI-DSS general controls overlap with ASVS (secure
  coding, encrypted transmission, logging), they are directly
  derived from ASVS and OWASP Top 10. Adopting PCI-DSS would
  force a mapping to ASVS-equivalents anyway, without adding
  coverage.

### OWASP MASVS (Mobile Application Security Verification Standard)

The mobile-app sibling of ASVS.

**Rejected** because:

- MASVS is scoped to mobile client applications. agent-auth is
  a local HTTP service consumed by other programs; there is no
  mobile client.
- The MASVS categories that would still apply (cryptography,
  authentication, code quality) are direct ports of the
  equivalent ASVS categories; adopting MASVS gains nothing.

### CWE Top 25 / SANS Top 25 weakness lists

Public catalogues of the most common software weaknesses.

**Rejected** because:

- Weakness catalogues, not verification standards. They tell a
  developer what to avoid, not what to verify. No L1 / L2 / L3
  bar means no stopping point for a per-plan walk.
- Already implicitly covered by `ruff`, `shellcheck`, and the
  dependency-audit gates — the weakness classes the Top 25
  names are discovered by the existing static tooling.

### Rely on NIST SP 800-53 alone

Keep the existing cybersecurity standard and treat
application-surface concerns as implicit in SI (System and
Information Integrity) and SC (System and Communications
Protection).

**Rejected** because:

- SP 800-53 families are organisational — they assume the
  application is one of many subsystems inside a larger
  accreditation boundary. The family granularity is too coarse
  to walk per-endpoint or per-request.
- Leaves the per-plan standards walk with no concrete
  application-surface checklist. Application concerns keep
  getting rediscovered during code review rather than verified
  against a shared list.

### Name no application-security standard

Leave the application side implicit and rely on `SECURITY.md`'s
STRIDE threat model plus the existing SP 800-53 walk.

**Rejected** because:

- `SECURITY.md`'s threat model is structured by STRIDE category
  (Spoofing / Tampering / Repudiation / …), not by
  application-surface chapter. A PR author walking the threat
  model can see the six categories but cannot see which ASVS
  chapter each mitigation discharges.
- Every future application-surface PR would have to
  rediscover which concerns are in scope from first principles.

## Decision

Adopt **OWASP ASVS v5** as the project's application-security
verification standard, targeting **Level 2 (L2)**.

- Per-chapter conformance lives in `design/ASVS.md`, structured
  by the 17 ASVS v5 chapters (V1 … V17) with conformance
  recorded as Implemented / Partial / Planned / Not applicable
  and evidence cited per row.
- `SECURITY.md` grows a new `## Application security standard`
  section that names ASVS v5, states the target level (L2),
  links `design/ASVS.md`, and cross-references the companion
  standards (SP 800-53 for system controls, SSDF for SDLC
  practices, SLSA / cosign / SBOM for supply chain).
- `scripts/verify-standards.sh` asserts the
  `## Application security standard` section exists in
  `SECURITY.md` — the existence of the pointer is gated; the
  content of `design/ASVS.md` is not.
- Per-plan application-surface walks use `design/ASVS.md`
  alongside the existing SP 800-53 control walk and SSDF
  practice walk. Gaps identified during a plan are tracked as
  GitHub issues linked from the relevant `design/ASVS.md` row.

## Consequences

- The per-PR standards walk gains a concrete application-surface
  checklist. Application concerns (input validation, session
  management, secure defaults, cryptography choices, transport
  protection) now surface against a named chapter rather than
  being tribal knowledge inside `SECURITY.md`'s threat-model
  tables.
- Seven existing open issues (#6 plugin boundary, #100 audit
  schema unification, #101 TLS between devcontainer and host,
  #102 rate limiting, #103 audit cryptographic chaining,
  #117 OpenAPI specs, and ADR 0016 supply-chain follow-ups)
  now have an application-standard home: the relevant ASVS
  chapter is where their gap is recorded. No new issues are
  opened by this ADR — the audit confirmed every gap it found
  was already tracked.
- `design/ASVS.md` becomes a living document that future plans
  must update in the same PR as the change, mirroring how
  `SECURITY.md` and `design/SSDF.md` are refreshed before
  security-relevant changes land.
- ASVS is a verification standard, not a conformance regime —
  the project does not claim ASVS-verified status under any
  formal certification scheme, only that it uses ASVS v5 at
  target L2 to structure its application-surface evidence. No
  third-party audit is implied.
- Adopting ASVS does not change the project's QM-level
  assurance declaration in `design/ASSURANCE.md`. ASVS sits
  alongside SSDF and ASSURANCE.md as per-change checklists;
  ASSURANCE.md remains the ISO-9000-style *what must ship*,
  SSDF is the *how the project builds it*, ASVS is the
  *what the application verifies*, and SP 800-53 is the *what
  the running system controls*.

## Follow-ups

- Per-chapter gap issues are already tracked by their existing
  GitHub issues (linked from `design/ASVS.md`). No new issues
  are opened by this ADR.
- If a browser-facing management UI is ever added, ASVS V3
  (Web Frontend Security) moves from "Not applicable" to
  in-scope and must be walked in the introducing PR.
- If an OAuth / OIDC front-end is ever added (e.g. to integrate
  with an enterprise IdP), ASVS V10 (OAuth and OIDC) likewise
  becomes in-scope.
