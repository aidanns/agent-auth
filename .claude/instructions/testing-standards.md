# Testing Standards

Rules for how tests should be written and what coverage to maintain.

## Test design

- **Tests exercise public APIs only** — a test exercises the public API of
  the unit under test, and only the public API. For the CLI that means argv
  in, stdout (including `--json`) out, and subsequent CLI invocations to
  observe state. Do not open the SQLite store, inspect keyring internals, or
  read audit-log byte layout in CLI tests. Name each unit's public surface
  before writing tests.
- **End-to-end test layer** — maintain at least one end-to-end test that
  drives the full lifecycle: CLI creates a token, server validates it for an
  allow-tier scope, refresh rotates the pair, JIT approval gates a
  prompt-tier scope, revocation invalidates subsequent use.
- **Integration-test isolation** — integration tests must not bind to shared
  ports or assume exclusive access to host resources. Use containers,
  per-test network namespaces, or equivalent so tests don't race when run in
  parallel or on CI with concurrent jobs.

## Coverage

- **Line and branch coverage threshold** — run `pytest-cov` in CI with a
  starting threshold that ratchets upward. Never lower the threshold without
  explicit justification.
- **Mutation testing on security-critical paths** — run `mutmut` or
  `cosmic-ray` against security-critical modules (e.g. token generation,
  cryptography, scope enforcement) to surface weak assertions. A line being
  "covered" does not mean the test would fail if the line were wrong.
- **Chaos and fault-injection tests** — add a fault-injection test layer that
  forces error conditions: keyring throws, DB is locked, disk is full, plugin
  times out. The happy path is not enough.

## Performance

- **Benchmark suite** — maintain a benchmark suite (e.g. `pytest-benchmark`
  for microbenchmarks, `locust` or `k6` for HTTP load) and run it in CI on a
  schedule to catch regressions.
- **Performance budget** — document a latency target for critical endpoints
  (e.g. `/validate` p95) in `design/DESIGN.md` and add at least one test
  that asserts the budget.
