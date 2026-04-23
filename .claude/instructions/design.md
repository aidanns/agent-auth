<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Design Documentation

How system design, functional decomposition, and product breakdown should
be documented.

## Design directory structure

Every project should maintain a `design/` directory containing:

- **`DESIGN.md`** — system design document describing the architecture,
  interfaces, and behaviour.
- **`ASSURANCE.md`** — QM / SIL level declaration and verification results.
- **`decisions/`** — Architecture Decision Records (see below).
- **`functional_decomposition.yaml`** — hierarchical breakdown of system
  functions (see below).
- **`product_breakdown.yaml`** — hierarchical breakdown of system components
  and deliverables (see below).

## Architecture Decision Records

For each significant design decision, write a short ADR in
`design/decisions/`. Capture the context (what prompted the decision),
the decision itself, and the consequences (trade-offs accepted,
alternatives rejected). ADRs survive beyond commit messages and make
the rationale discoverable for future contributors.

## Functional decomposition

Document the system's functional decomposition in
`design/functional_decomposition.yaml`. This is a hierarchical breakdown
of the system's functions — what the system does, decomposed into
progressively finer-grained capabilities. Each leaf function should be
traceable to tests via a function-to-test allocation mechanism — decide
on an annotation format for tests to declare which design functions they
exercise, and apply it (see `testing-standards.md`). The YAML schema
must match the format expected by the
`systems-engineering` CLI (`systems-engineering function verify`).

## Product breakdown

Document the system's product breakdown in
`design/product_breakdown.yaml`. This is a hierarchical breakdown of the
system's components and deliverables — what the system is made of,
decomposed into progressively finer-grained parts (modules, packages,
config files, scripts, etc.). The YAML schema must match the format
expected by the `systems-engineering` CLI.

## Quality management / safety integrity level

Declare a quality-management level (ISO 9000) or safety-integrity level
(IEC 61508) in `design/ASSURANCE.md`. This is a project-level decision
made once. Implementation plans should verify the implementation meets
the required activities, documentation, and evidence for the declared
level (see `plan-template.md`).

## Cybersecurity standard

Select a cybersecurity standard appropriate to the project (e.g. ISM,
NIST SP 800-53) and record the choice in `SECURITY.md`. This is a
project-level decision made once, not a per-plan step. Implementation
plans should verify compliance against the chosen standard (see
`plan-template.md`).

## Rendered design artefacts

`functional_decomposition.yaml` and `product_breakdown.yaml` are the
source of truth, but the repo also ships rendered variants for
human browsing (`.md` tables, `.csv` exports, `.d2` / `.svg` / `.png`
diagrams) so reviewers do not have to run the generator to read the
design. Because these variants are generated, any change to the yaml
makes them stale unless they are regenerated.

Wire a generator task and a CI drift gate:

- **Generator script** — a `scripts/design-generate.sh` that runs the
  `systems-engineering` CLI over each yaml and writes the rendered
  artefacts into `design/` in place. Expose it as
  `task design:generate` so developers have one command to refresh
  everything.
- **CI drift gate** — extend the existing design-verification script
  to run the generator and then `git diff --exit-code -- design/`.
  If the checked-in artefacts differ from what the generator produces
  right now, the workflow fails with a pointer at
  `task design:generate`.
- **Licensing** — the `systems-engineering` generator does not emit
  inline SPDX headers. Cover the rendered variants with a REUSE.toml
  override block rather than post-processing SPDX comments into the
  generator output. Hand-written design docs (DESIGN.md, ASSURANCE.md,
  etc.) keep their inline SPDX headers.

## Keeping design docs current

After implementation, verify that the functional decomposition, product
breakdown, and `design/DESIGN.md` reflect the current state of the system.
Add new functions, components, or design sections as the system evolves.
Remove entries for functionality that has been deleted. Regenerate the
rendered artefacts (`task design:generate`) whenever the yaml changes;
the CI drift gate fails otherwise.
