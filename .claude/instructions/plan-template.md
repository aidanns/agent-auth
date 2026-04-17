# Plan Template Requirements

Every implementation plan must include the following steps where applicable.
Skip a step only when the project clearly does not need it (e.g. no DB means
no migration strategy), and note the skip in the plan.

## Design and verification

- **Verify implementation against design doc** — after implementation, diff
  behaviour and schema against `design/DESIGN.md`, reconcile any drift, and
  either fix the code or update the design.
- **Threat model** — produce or refresh a STRIDE / attack-tree threat model
  in `design/` before making security-relevant changes. The threat model
  drives SECURITY.md, standards compliance, rate limiting, and key recovery
  design.
- **Architecture Decision Records** — for each significant design decision,
  write a short ADR in `design/decisions/`. Capture the context, decision,
  and consequences so the rationale survives beyond commit messages.
- **Cybersecurity standard compliance** — pick a standard appropriate to the
  project (e.g. ISM, NIST SP 800-53), walk the relevant controls, record
  results in `design/`, and raise issues for gaps.
- **Declare and verify QM / SIL level** — declare a quality-management level
  (ISO 9000) or safety-integrity level (IEC 61508) in the README and/or
  `design/`, then verify the implementation meets the required activities,
  documentation, and evidence.

## API and schema

- **API versioning strategy** — decide on URL-versioned, header-versioned, or
  major-version-bump, document in `design/DESIGN.md`, and apply it.
- **Stable error taxonomy** — document all HTTP error strings and their
  stability guarantees in `design/DESIGN.md`. These are a public API.
- **DB schema migration strategy** — add a `schema_version` table and a
  simple idempotent migration mechanism for any project with persistent
  storage.
- **Audit-log schema** — treat the on-disk log format as a public API. Pin
  every field's name and type with tests.

## Security

- **SECURITY.md** — create one covering trust boundaries, threat model, key
  handling, revocation flow, audit surface, and vulnerability reporting.
  Reference from README.
- **Rate limiting / DoS posture** — decide an expected request rate and
  ceiling, document in `design/DESIGN.md`, and implement or explicitly note
  why it is not required.
- **Key recovery and loss scenarios** — design a deliberate recovery / backup
  / warning flow for when secrets are lost (e.g. keychain wipe).
- **Plugin / extension trust boundary** — when the process holds secrets, any
  plugin surface should default to out-of-process (HTTP, IPC) so third-party
  code never crosses the trust boundary.
- **Enumerate distinct byte/type classes** — before writing code that handles
  security-critical values, list every semantically distinct type at the
  boundary (ciphertext vs plaintext, signing key vs encryption key, etc.)
  and ensure each has a `NewType` or equivalent.

## Testing

- **Create or verify test runner script** — ensure `scripts/test.sh` (or
  equivalent) exists so the full test suite runs with one command.
- **Wire all check scripts into CI** — every repeatable check script
  (`scripts/test.sh`, `scripts/verify-*.sh`) must have a GitHub Actions
  workflow.
- **Function-to-test allocation** — decide on an annotation mechanism for
  tests to declare which design functions they exercise, document it, and
  apply it so `scripts/verify-function-tests.sh` passes.
- **End-to-end tests** — add a test layer that drives the full lifecycle
  (create -> validate -> refresh -> JIT approve -> revoke).
- **Integration-test isolation** — pick containers, per-test network
  namespaces, or equivalent so tests don't race on shared ports.
- **Performance testing** — add a benchmark suite and run it in CI on a
  schedule to catch regressions.
- **Performance budget** — pick a latency target (e.g. `/validate` p95),
  document in `design/DESIGN.md`, and add a test that asserts it.

## Coding standards check

- **Apply coding standards from `coding-standards.md`** — after
  implementation, review the changes against the coding standards
  (naming, types, config, XDG paths, plugin surfaces). This catches
  issues like implicit units in names, raw tuples for structured keys,
  missing `NewType` wrappers, config defaults written to disk, and
  duplicate config sources.

## Operations

- **Observability design** — document log schema, log levels, retention
  policy, log location (per XDG: `$XDG_STATE_HOME`), and any emitted metrics.
- **Health-check endpoint** — add `GET /agent-auth/healthz` returning 200
  when keys load and the DB is readable.
- **Metrics endpoint** — add `GET /agent-auth/metrics` with
  Prometheus-compatible output covering request counts, latency, token
  operations, validation decisions, and cache sizes.
- **Graceful shutdown** — design and test shutdown behaviour so in-flight
  requests (especially JIT approvals) complete cleanly on SIGTERM.
