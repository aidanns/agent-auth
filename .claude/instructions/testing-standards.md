# Testing Standards

Rules for how tests should be written and what coverage to maintain.

## Test design

- **Tests exercise public APIs only** — a test exercises the public API of
  the unit under test, and only the public API. For a CLI that means argv in
  and stdout/stderr out; for an HTTP service that means requests and
  responses; for a library that means the exported interface. Do not reach
  into internal storage, private state, or implementation details. Name each
  unit's public surface before writing tests.
- **End-to-end test layer** — maintain at least one end-to-end test that
  drives the full user-facing lifecycle of the system.
- **Integration-test isolation** — integration tests must not bind to shared
  ports or assume exclusive access to host resources. Use containers,
  per-test network namespaces, or equivalent so tests don't race when run in
  parallel or on CI with concurrent jobs.

## Coverage

- **Line and branch coverage threshold** — run a coverage tool in CI with a
  starting threshold that ratchets upward. Never lower the threshold without
  explicit justification.
- **Mutation testing on security-critical paths** — run a mutation testing
  tool against security-critical modules to surface weak assertions. A line
  being "covered" does not mean the test would fail if the line were wrong.
- **Chaos and fault-injection tests** — add a fault-injection test layer that
  forces error conditions: external service failures, storage errors, disk
  full, plugin timeouts. The happy path is not enough.

## Performance

- **Benchmark suite** — maintain a benchmark suite and run it in CI on a
  schedule to catch regressions.
- **Performance budget** — document a latency target for critical operations
  in the design docs and add at least one test that asserts the budget.
