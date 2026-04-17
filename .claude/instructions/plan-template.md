# Plan Template Requirements

Every implementation plan must include the following steps where applicable.
Skip a step only when the project clearly does not need it (e.g. no DB means
no migration strategy), and note the skip in the plan. Where the project
already has established standards or conventions, follow those; use these
defaults where nothing is already in place.

## Design and verification

- **Verify implementation against design doc** — after implementation, diff
  behaviour and schema against the design doc, reconcile any drift, and
  either fix the code or update the design.
- **Threat model** — produce or refresh a STRIDE / attack-tree threat model
  in `SECURITY.md` before making security-relevant changes. The threat model
  drives standards compliance, rate limiting, and key recovery design.
- **Architecture Decision Records** — for each significant design decision,
  write a short ADR in `design/decisions/`. Capture the context, decision,
  and consequences so the rationale survives beyond commit messages.
- **Cybersecurity standard compliance** — verify the implementation against
  the project's chosen cybersecurity standard (see `design.md`), walk the
  relevant controls, and raise issues for gaps.
- **Verify QM / SIL compliance** — verify the implementation meets the
  activities, documentation, and evidence required by the project's declared
  QM / SIL level (see `design.md`).

## Testing

- **Create or verify test runner script** — ensure a single-command test
  runner exists (e.g. `scripts/test.sh`) so the full test suite runs with
  one command.
- **Wire all check scripts into CI** — every repeatable check script must
  have a CI workflow.
- **Function-to-test allocation** — decide on an annotation mechanism for
  tests to declare which design functions they exercise, and apply it.
- **End-to-end tests** — add a test layer that drives the full user-facing
  lifecycle of the system.
- **Integration-test isolation** — pick containers, per-test network
  namespaces, or equivalent so tests don't race on shared ports.
- **Performance testing** — add a benchmark suite and run it in CI on a
  schedule to catch regressions.
- **Performance budget** — pick a latency target for critical endpoints,
  document it, and add a test that asserts the budget.

## Post-implementation standards review

- **Apply coding standards from `coding-standards.md`** — review the changes
  against the coding standards (naming, types). This catches issues like
  missing verb names on procedures, implicit units in names, raw tuples
  for structured keys, and missing newtype wrappers.
- **Apply service design standards from `service-design.md`** — review the
  changes against the service design standards (config, file paths, plugin
  surfaces, HTTP services, security, resilience). This catches issues like
  config defaults written to disk, duplicate config sources, wrong XDG
  paths, missing health endpoints, and missing graceful shutdown.
- **Apply release and hygiene standards from `release-and-hygiene.md`** —
  verify required project files exist, structured output schemas are pinned,
  and versioning is derived from VCS tags.
- **Apply testing standards from `testing-standards.md`** — review tests
  against the testing standards. Verify tests exercise public APIs only
  (not internal persistence), name each unit's public surface, and that
  integration tests are properly isolated.
