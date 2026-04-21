<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: `/metrics` Prometheus Endpoint (#26)

Closes #26.

## Summary

Implement `GET /agent-auth/metrics` and `GET /things-bridge/metrics`
emitting Prometheus text exposition format. Metrics are hand-rolled
(no `prometheus_client` or OpenTelemetry SDK dependency — see ADR
0017, which pins OTel semconv *names* but does not mandate the SDK).

Existing design anchors:

- `design/DESIGN.md` "Observability" pre-declares the HTTP metric
  names and types. Domain counter names were deferred to this work.
- `scripts/verify-standards.sh` already exempts `/metrics` from the
  versioning gate.

## Design verification

No new ADR. Decisions:

- **Auth on `/metrics`**: require a `:metrics` scope, parallel to
  `/health`. The server already binds 127.0.0.1-only, but
  authenticating the endpoint matches the `/health` model and makes
  the surface uniform for future remote-operator workflows.
- **Histogram buckets**: OTel-recommended HTTP latency buckets
  (`0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10`).
- **Shared primitives**: new `src/server_metrics/` package holds the
  `Counter` / `Gauge` / `Histogram` / `Registry` primitives and the
  Prometheus text formatter. Both services import from it. Matches
  the existing `things_client_common` precedent for cross-service
  library code.
- **Instrumentation scope**: HTTP duration histogram + active-requests
  gauge are emitted on every endpoint (including `/health` and
  `/metrics` itself); domain counters live only on agent-auth.

## Metrics catalogue

### Agent-auth

| Name                                   | Type      | Labels                                                       |
| -------------------------------------- | --------- | ------------------------------------------------------------ |
| `http_server_request_duration_seconds` | histogram | `method`, `route`, `status_code`                             |
| `http_server_active_requests`          | gauge     | `method`                                                     |
| `agent_auth_token_operations_total`    | counter   | `operation` (created, refreshed, reissued, revoked, rotated) |
| `agent_auth_validation_outcomes_total` | counter   | `outcome` (allowed, denied), `reason`                        |
| `agent_auth_approval_outcomes_total`   | counter   | `outcome` (approved, denied)                                 |

`reason` values for validation outcomes mirror the audit-log
`validation_denied` reasons plus `ok` for `validation_allowed`:
`invalid_token`, `not_access_token`, `token_not_found`,
`token_expired`, `family_revoked`, `scope_denied`, `approval_denied`,
`ok`.

### Things-bridge

| Name                                   | Type      | Labels                           |
| -------------------------------------- | --------- | -------------------------------- |
| `http_server_request_duration_seconds` | histogram | `method`, `route`, `status_code` |
| `http_server_active_requests`          | gauge     | `method`                         |

Things-bridge has no persistent state; its domain events (authz
outcomes, Things-app failures) are reflected in the HTTP status
labels on the duration histogram.

## Wiring points

- `src/server_metrics/` — new package. `__init__.py` re-exports
  primitives. `registry.py` holds `Counter`, `Gauge`, `Histogram`,
  `Registry`. `formatter.py` holds `render_prometheus_text`.
- `src/agent_auth/metrics.py` — constructs the registry + named
  metrics.
- `src/agent_auth/server.py`:
  - `AgentAuthServer.__init__` takes a `registry` + `metrics` dict.
  - New `/agent-auth/metrics` GET handler: `_require_scope_auth`
    with scope `agent-auth:metrics`, respond 200 text/plain;
    version=0.0.4.
  - `handle_one_request` (or an explicit dispatch wrapper)
    brackets every request with a start timer + active-requests
    inc/dec, records `(method, route, status_code)` on return.
  - Instrument validate/refresh/reissue/token_create/modify/
    revoke/rotate handlers at the relevant success/failure points.
  - `ApprovalManager.request_approval` takes optional metrics
    hook to increment `approval_outcomes_total`.
- `src/things_bridge/metrics.py` + `server.py`: same HTTP-level
  instrumentation only.
- `run_server` in both services: build registry, pass into server
  constructor.

### Route-template problem

Per-request `route` label cannot be the raw `self.path` — id-carrying
paths like `/things-bridge/v1/todos/ABC123` would blow label
cardinality. Map to templated routes matching the OpenAPI path
entries: `/things-bridge/v1/todos/{id}`, etc. Implementation: each
handler function is responsible for setting a
`self._route_template` string on itself before returning, which the
post-dispatch wrapper reads and passes into `observe()`. Unknown
routes map to `/unknown`.

## Tests

- `tests/test_server_metrics.py` — unit tests for the primitives:
  counter monotonicity, gauge inc/dec, histogram bucket semantics,
  label-value escaping, Prometheus-text round-trip through a
  parser (use the `openapi-spec-validator`-style approach: validate
  shape, not just grep).
- `tests/test_server.py` — new metrics-endpoint unit tests: 401 on
  missing token, 403 on missing scope, 200 with text/plain body on
  authorised, body contains each required metric name, domain
  counters increment on validate / approval success+denial / token
  ops.
- `tests/test_things_bridge_server.py` — equivalent for bridge.
- `tests/integration/agent_auth/test_metrics.py` — scrape via Docker
  compose, assert metric names.
- `tests/integration/things_bridge/test_bridge.py` — add analogous
  integration scrape.
- `tests/test_error_taxonomy.py` — add `/metrics` `missing_token`,
  `invalid_token`, `token_expired`, `scope_denied` coverage rows.
- `tests/test_openapi_spec.py` — no change (contract test walks
  registered handlers; /metrics lands automatically).

## Docs

- `design/DESIGN.md` "Observability" — fill in the domain-counter
  table, note the label sets and escape rules.
- `design/error-codes.md` — add `/metrics` entry mirroring
  `/health` entries.
- `openapi/agent-auth.v1.yaml`, `openapi/things-bridge.v1.yaml` —
  add `/metrics` paths (text/plain response schema).
- `CLAUDE.md` "Project-specific notes" — note that `/metrics` now
  exists.
- `CHANGELOG.md` — `### Added` entry under `[Unreleased]`.
- `CONTRIBUTING.md` / `README.md` — no updates needed.

## Regression check

Append to `scripts/verify-standards.sh` (after the health block):

- Grep `"/agent-auth/metrics"` / `"/things-bridge/metrics"` in each
  server module.
- Walk test files for a function block that references the route
  and asserts status 200 AND references at least one required
  metric name (e.g. `http_server_request_duration_seconds`).

## Post-implementation standards review

Per `.claude/instructions/plan-template.md`:

- Coding standards review (naming, types, safety).
- Service-design review (config, file paths, HTTP, resilience).
- Release / hygiene (CHANGELOG, OpenAPI, error taxonomy).
- Testing standards (public API only, named coverage).
- Tooling / CI (no new workflow needed; existing gates pick up
  the new code).

## Out of scope

- OTLP export (keeps us off the OTel SDK).
- Per-token or per-family cardinality (privacy + cost).
- Histogram buckets configurable per-endpoint (one global choice).
- Metrics persistence across restarts (accepted — counters reset).
