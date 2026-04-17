# Plan Template Requirements

Every implementation plan must include the following steps where applicable.
Skip a step only when the project clearly does not need it (e.g. no DB means
no migration strategy), and note the skip in the plan.

## Design and verification

- **Verify implementation against design doc** — after implementation, diff
  behaviour and schema against the design doc, reconcile any drift, and
  either fix the code or update the design.
- **Threat model** — produce or refresh a STRIDE / attack-tree threat model
  before making security-relevant changes. The threat model drives
  SECURITY.md, standards compliance, rate limiting, and key recovery design.
- **Architecture Decision Records** — for each significant design decision,
  write a short ADR. Capture the context, decision, and consequences so the
  rationale survives beyond commit messages.
- **Cybersecurity standard compliance** — pick a standard appropriate to the
  project (e.g. ISM, NIST SP 800-53), walk the relevant controls, record
  results, and raise issues for gaps.
- **Declare and verify QM / SIL level** — declare a quality-management level
  (ISO 9000) or safety-integrity level (IEC 61508) in the README and/or
  design docs, then verify the implementation meets the required activities,
  documentation, and evidence.

## API and schema

- **API versioning strategy** — decide on URL-versioned, header-versioned, or
  major-version-bump, document it, and apply it.
- **Stable error taxonomy** — document all error codes/strings and their
  stability guarantees. These are a public API.
- **DB schema migration strategy** — add schema version tracking and a simple
  idempotent migration mechanism for any project with persistent storage.
- **Audit-log schema** — treat the on-disk log format as a public API. Pin
  every field's name and type with tests.

## Security

- **SECURITY.md** — create one covering trust boundaries, threat model, key
  handling, revocation flow, audit surface, and vulnerability reporting.
  Reference from README.
- **Rate limiting / DoS posture** — decide an expected request rate and
  ceiling, document it, and implement or explicitly note why it is not
  required.
- **Key recovery and loss scenarios** — design a deliberate recovery / backup
  / warning flow for when secrets are lost.
- **Plugin / extension trust boundary** — when the process holds secrets, any
  plugin surface should default to out-of-process (HTTP, IPC) so third-party
  code never crosses the trust boundary.
- **Enumerate distinct byte/type classes** — before writing code that handles
  security-critical values, list every semantically distinct type at the
  boundary (e.g. ciphertext vs plaintext, signing key vs encryption key) and
  ensure each has a newtype or equivalent.

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
  against the coding standards (naming, types, config, file paths, plugin
  surfaces). This catches issues like implicit units in names, raw tuples
  for structured keys, missing newtype wrappers, config defaults written
  to disk, and duplicate config sources.
- **Apply testing standards from `testing-standards.md`** — review tests
  against the testing standards. Verify tests exercise public APIs only
  (not internal persistence), name each unit's public surface, and that
  integration tests are properly isolated.

## Operations

- **Observability design** — document log schema, log levels, retention
  policy, log location (per XDG: `$XDG_STATE_HOME`), and any emitted metrics.
- **Health-check endpoint** — add a health endpoint that returns 200 when
  critical subsystems (keys, DB, etc.) are healthy.
- **Metrics endpoint** — add a metrics endpoint with Prometheus-compatible
  output covering request counts, latency, and domain-specific counters.
- **Graceful shutdown** — design and test shutdown behaviour so in-flight
  requests complete cleanly on SIGTERM.
