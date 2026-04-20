# Plan: Adopt NIST SSDF (SP 800-218) as SDLC standard

Issue: [#113](https://github.com/aidanns/agent-auth/issues/113).

Source standard: `.claude/instructions/design.md` — *Cybersecurity
standard* (pairs the SDLC-side standard with the existing NIST SP
800-53 selection in `SECURITY.md`).

## Goal

Record NIST SSDF (SP 800-218) as the project's SDLC-practices
standard and produce a per-practice conformance audit so future
feature plans can verify their SDLC posture against it.

1. Add `design/SSDF.md` walking the four SSDF practice groups
   (PO / PS / PW / RV) and recording per-practice conformance
   (Implemented / Partial / Planned / Not applicable) with
   references to the existing artefact (ADR, doc, script, issue)
   that satisfies or tracks it.
2. Name SSDF in `SECURITY.md` under a new `## SDLC standard`
   section, mirroring the existing `## Cybersecurity standard`
   section for NIST SP 800-53.
3. Backfill ADR 0014 explaining the SDLC / application-controls /
   build-provenance split (SSDF / ASVS-#112 / SLSA-#109) and why
   SSDF is the right SDLC-side anchor for a solo-maintainer,
   local-only auth project.
4. File follow-up issues for every SSDF practice that the audit
   classifies as `Partial` or `Planned` and that is not already
   tracked by an existing GitHub issue.

## Non-goals

- Selecting or documenting ASVS (#112) or implementing SLSA
  (#109) / cosign (#110) / SBOM (#111). Those are referenced from
  SSDF practices but owned by their own issues.
- Implementing any new SDLC practice. The audit records current
  state; gaps are tracked as follow-ups, not closed.
- Promoting the project's QM-level ASSURANCE declaration. SSDF
  sits alongside ASSURANCE.md as an SDLC-practice checklist, not
  a replacement for it.
- Adding a deterministic regression check for every PS/PW/PO/RV
  practice. Only the pointer from `SECURITY.md` is gated (see
  verify-standards change below).

## Deliverables

1. **`design/SSDF.md`** — opens with a short rationale paragraph
   (why SSDF, how it pairs with NIST SP 800-53 / ASVS / SLSA) and
   a per-practice conformance table. Table columns: *Practice*,
   *Task*, *Conformance*, *Evidence / gap*. Rows follow SSDF
   v1.1's numbering (PO.1.1 … RV.3.4). Each Partial / Planned row
   cites the tracking issue; each Implemented row cites an ADR,
   design-doc section, script, or workflow.
2. **`SECURITY.md` — new `## SDLC standard` section** between the
   existing `## Cybersecurity standard` section and
   `## Vulnerability reporting`. One paragraph naming SSDF
   (SP 800-218) and linking `design/SSDF.md`; one bullet list
   naming the four practice groups and their scope; one sentence
   recording that ASVS (#112) and SLSA (#109) are the
   application-controls and build-provenance companions.
3. **`design/decisions/0014-nist-ssdf-sdlc-standard.md`** — ADR
   backfilling the decision. Status `Accepted — 2026-04-20`.
   Context captures the SDLC-vs-application-vs-supply-chain
   split. Considered alternatives covers (a) BSIMM (rejected —
   not publicly documented as a measurable standard), (b) OWASP
   SAMM (rejected — overlaps SSDF without adding per-practice
   rigour for a solo developer), (c) not naming any SDLC
   standard (rejected — breaks the `plan-template.md` standards
   walk for SDLC concerns). Decision names SSDF SP 800-218 v1.1.
   Consequences note the pairing with #112 / #109 / #110 / #111
   and the per-plan SDLC walk that now becomes possible.
4. **`design/decisions/README.md`** — adds entry linking ADR
   0014\.
5. **`scripts/verify-standards.sh`** — adds a new
   `sdlc-standard` entry to `security_sections`, enforcing that
   `SECURITY.md` contains a heading matching
   `## SDLC standard`. Regression-checkable mirror of the
   existing `cybersecurity-standard` gate.
6. **GitHub follow-up issues** — one per Partial / Planned
   practice that is not already tracked. Cross-link #113 as the
   originating audit.

## Approach

**Draft SSDF.md first.** Walk SSDF v1.1 top-down. For each task,
record current state from:

- existing ADRs (`design/decisions/0006`–`0013`),
- `design/ASSURANCE.md` (QM activities cover several PO / PW
  practices),
- `SECURITY.md` (threat-model entries cover PW.1 / RV.1),
- `CONTRIBUTING.md` (secure defaults, commit signing, pre-commit
  hooks cover PO.3 / PS.1),
- `scripts/verify-standards.sh` and `scripts/verify-dependencies.sh`
  (PO.3 toolchain evidence),
- GitHub Actions under `.github/workflows/` (PO.3 / PW.8),
- existing open issues (#6 plugin boundary, #102 rate limiting,
  #103 audit chaining, #106 autorelease, #109 SLSA, #110 cosign,
  #111 SBOM).

Each row lands in one of four buckets:

- **Implemented** — existing artefact satisfies the task today.
- **Partial** — partial coverage with a known gap; cite the
  issue tracking the remainder.
- **Planned** — task selected but not yet started; cite the
  issue.
- **Not applicable** — task is organisational (e.g. PO.2 roles /
  training / certification for a multi-person team) and does not
  fit a solo, local-only project. Record the rationale in-line
  so `plan-template.md` walkers can see why we skipped.

**Update SECURITY.md second.** Add the `## SDLC standard` section.
Keep the section short — details live in `design/SSDF.md`. The
section's existence is gated by `verify-standards.sh`; its
content is not.

**Write ADR 0014 third.** Follow `design/decisions/TEMPLATE.md`
exactly. Keep the ADR under one page of prose.

**Wire the gate last.** Extend `security_sections` in
`scripts/verify-standards.sh` with the new `sdlc-standard` entry.
Run `task verify-standards` locally for a green baseline, then
temporarily strip the new `## SDLC standard` heading and confirm
the gate reports the exact missing section.

**File follow-ups at the end.** After SSDF.md is complete, grep
its *Partial* / *Planned* rows and create a GitHub issue for each
one that isn't already covered by an existing open issue. Link
each new issue back to #113 and to the SSDF.md row (`design/SSDF.md#PO-4-2`
anchor or similar).

## Design and verification

- **Verify implementation against design doc** — SSDF.md is the
  design doc for SDLC conformance. Cross-check each row against
  the cited ADR / script / workflow; if the cited artefact does
  not implement the practice, downgrade Implemented → Partial /
  Planned and file the gap.
- **Threat model** — no new security-relevant behaviour. No
  `SECURITY.md` threat-model rows added. Skip.
- **Architecture Decision Records** — ADR 0014 *is* the design
  decision for this change. No other decisions fall out.
- **Cybersecurity standard compliance** — this change records
  the SDLC-side standard that pairs with NIST SP 800-53. Walk the
  NIST SP 800-53 SA (System and Services Acquisition) family
  against the new SSDF audit to confirm the two are consistent;
  if any SA control is stricter than its SSDF counterpart, note
  the delta in SSDF.md.
- **Verify QM / SIL compliance** — no change to the QM
  declaration. SSDF conformance is additive to ASSURANCE.md's
  Required-activities list; ASSURANCE.md itself is not modified.

## Post-implementation standards review

- **Coding standards** — docs + one shell-script gate. Verify the
  new `security_sections` entry uses the same `name|pattern`
  shape as its neighbours and stays inside the `keep-sorted`
  block.
- **Service design standards** — docs only. Skip.
- **Release and hygiene** — add a `CHANGELOG.md` `Unreleased`
  entry noting the SSDF adoption and the new gate. No versioning
  impact; no pinned-schema changes.
- **Testing standards** — no test files touched. The new gate is
  exercised by the existing `task verify-standards` CI job.
- **Tooling and CI standards** — gate runs under the existing
  `task verify-standards` target; no new tool added.

## Follow-ups

- ASVS application-security standard — tracked in
  [#112](https://github.com/aidanns/agent-auth/issues/112).
- SLSA build provenance — tracked in
  [#109](https://github.com/aidanns/agent-auth/issues/109).
- Cosign artifact signing — tracked in
  [#110](https://github.com/aidanns/agent-auth/issues/110).
- SPDX SBOM publication — tracked in
  [#111](https://github.com/aidanns/agent-auth/issues/111).
- Per-practice gap issues filed during the audit (linked from
  the relevant rows of `design/SSDF.md`).
