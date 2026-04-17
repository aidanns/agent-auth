# Design Documentation

How system design, functional decomposition, and product breakdown should
be documented.

## Design directory structure

Every project should maintain a `design/` directory (see
`release-and-hygiene.md` for the full list of expected contents).

## Functional decomposition

Document the system's functional decomposition in
`design/functional_decomposition.yaml`. This is a hierarchical breakdown
of the system's functions — what the system does, decomposed into
progressively finer-grained capabilities. Each leaf function should be
traceable to tests (see `testing-standards.md` function-to-test
allocation). The YAML schema must match the format expected by the
`systems-engineering` CLI (`systems-engineering function verify`).

## Product breakdown

Document the system's product breakdown in
`design/product_breakdown.yaml`. This is a hierarchical breakdown of the
system's components and deliverables — what the system is made of,
decomposed into progressively finer-grained parts (modules, packages,
config files, scripts, etc.). The YAML schema must match the format
expected by the `systems-engineering` CLI.

## Cybersecurity standard

Select a cybersecurity standard appropriate to the project (e.g. ISM,
NIST SP 800-53) and record the choice in `design/SECURITY.md`. This is a
project-level decision made once, not a per-plan step. Implementation
plans should verify compliance against the chosen standard (see
`plan-template.md`).

## Keeping design docs current

After implementation, verify that the functional decomposition, product
breakdown, and `design/DESIGN.md` reflect the current state of the system.
Add new functions, components, or design sections as the system evolves.
Remove entries for functionality that has been deleted.
