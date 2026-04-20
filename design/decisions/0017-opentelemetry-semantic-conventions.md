<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
SPDX-License-Identifier: MIT
-->

# ADR 0017 — Adopt OpenTelemetry semantic conventions for metrics and logs

## Status

Accepted — 2026-04-20.

## Context

Issue [#118](https://github.com/aidanns/agent-auth/issues/118) asks
that the not-yet-built Prometheus `/metrics` endpoints (#26) and the
not-yet-schema-pinned audit log (#20) emit attribute names an operator
recognises without project-specific adapters. The
[OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
define stable names for common HTTP-server attributes
(`http.request.method`, `http.response.status_code`, `http.route`,
`url.scheme`, `server.address`, `client.address`, `service.name`,
`service.version`, `user_agent.original`, …) and metric names for
HTTP-server signals (`http.server.request.duration`,
`http.server.active_requests`).

Without this decision, #26 and #20 would each invent their own
attribute keys and metric names. Observability tooling (Grafana
dashboards, Loki queries, APM rules) would then have to carry a
per-project mapping layer. `.claude/instructions/service-design.md`
requires an observability design; it does not mandate a specific
vocabulary. Committing to OTel semconv now unblocks #26/#20/#33 with
a shared standard and avoids a later rename.

The project emits:

- Prometheus text on `/metrics` (planned — #26). Metric names use
  the Prometheus convention that replaces `.` with `_` and appends
  units (`_seconds`, `_bytes`).
- JSON-lines audit logs to `$XDG_STATE_HOME/agent-auth/audit.log`.
  Fields are flat JSON keys, not nested OTel LogRecord envelopes.

Neither surface uses the OpenTelemetry SDK or wire protocol. The
commitment is to the *attribute-naming conventions*, not to adopting
the SDK or OTLP transport.

## Considered alternatives

### Invent project-specific metric and attribute names

Pick readable names tuned for this project (e.g. `validate_latency`,
`request_method`).

**Rejected** because every operator tool that ingests the telemetry
has to learn a new vocabulary, and the next time a related project
(a second bridge, a separate auth component) emits telemetry it
picks different names by default — so the divergence compounds.

### Adopt the full OpenTelemetry SDK and OTLP export

Use the `opentelemetry-sdk` Python package, wire spans, metrics, and
logs through an OTLP exporter, run a local collector.

**Rejected** because the project is a single-user localhost service
with no external collector in its trust boundary. The SDK adds
runtime weight (and a new dependency surface) for a problem the
project doesn't have. Semconv-compliant Prometheus text and
JSON-lines give operators the benefit of the conventions without
inheriting the SDK's shape. If the project later wants OTLP, the
attribute names are already correct.

### Defer the naming decision to #26 / #20

Wait until the first implementation lands, pick names ad-hoc, write
the ADR after.

**Rejected** because the whole point of the semconv choice is to
constrain #26 and #20 before they commit to names. Deciding after
each lands forces a rename or a documented deviation per issue.

## Decision

Adopt the OpenTelemetry semantic conventions, pinned to
[v1.40.0](https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.40.0)
(released 2026-02-19 — the latest stable release at the time of
adoption). The pin refers to the semconv repository's tagged
release, not to any particular SDK version.

Concretely:

1. HTTP-server metrics emitted by #26 use the semconv names
   `http.server.request.duration` (Histogram instrument, seconds)
   and `http.server.active_requests` (UpDownCounter instrument),
   mapped to Prometheus exposition names per the OTel → Prometheus
   mapping spec (`.` → `_`, unit suffix). The duration histogram
   carries `http.request.method`, `http.route`, `url.scheme`,
   `http.response.status_code` (conditionally required whenever a
   status was received/sent), and `error.type` (conditionally
   required whenever the request ended with an error — including
   5xx responses, where both attributes apply). The active-requests
   UpDownCounter carries `http.request.method` and `url.scheme` as
   its required attributes; `server.address` / `server.port` are
   opt-in per semconv and this project emits them (localhost binds
   vary per service).
2. Audit log HTTP request metadata uses semconv HTTP attribute
   keys: `http.request.method`, `http.route`, `url.path`,
   `http.response.status_code`, `url.scheme`, `client.address`,
   `user_agent.original`, `network.protocol.version`,
   `server.address`, `server.port`. `http.route` is the templated
   path (metrics-safe, low cardinality); `url.path` is the actual
   path with concrete IDs (forensics-useful). Emitter identity uses
   semconv **resource** attributes (a distinct namespace in semconv):
   `service.name` and `service.version`. #20 enforces all of this
   via the audit schema contract tests.
3. Domain-specific metrics (validation outcomes, token operations,
   JIT approval outcomes) and domain-specific audit fields (those
   describing tokens, scopes, tiers, approval outcomes) use
   project-namespaced names outside the OTel semconv namespace —
   they have no OTel equivalent and inventing semconv extensions
   for them is out of scope. The concrete metric names and label
   sets are designed with #26 (metrics endpoint); this ADR only
   fixes the namespace, not the schema. The existing audit-log
   domain fields (`event`, `token_id`, `family_id`, `scope`,
   `scopes`, `tier`, `grant_type`, `reason`) keep their current
   names.
4. The version pin is declared in `design/DESIGN.md` and revisited
   when a semconv change would affect an attribute the project
   already emits. Bumping the pin is itself an ADR-worthy decision
   when it requires renaming.

The full mapping lives in the `## Observability` section of
`design/DESIGN.md`. This ADR is the decision record; DESIGN.md is
the reference.

## Consequences

- #26 (metrics endpoint) must use the metric and attribute names
  listed above. The verify-standards regression check that lands
  with #26 should grep for the semconv-mapped Prometheus names.
- #20 (audit log schema pinning) must introduce the HTTP-attribute
  fields above using the semconv keys when it adds them (the audit
  log today emits only domain fields — no HTTP attribute fields
  exist yet to rename), and bump the documented schema version.
  Domain fields (`event`, `family_id`, `token_id`, `scope`,
  `scopes`, `tier`, `grant_type`, `reason`) keep their names.
- #33 (observability design document) references this ADR for the
  naming commitment and folds the DESIGN.md summary into the
  dedicated observability doc it produces.
- Prometheus exposition replaces `.` with `_` and suffixes units
  (`http_server_request_duration_seconds`) per the OTel → Prometheus
  mapping spec.
- `timestamp` remains the JSON key in audit lines (not `Timestamp`).
  The project emits flat JSON objects, not OTel LogRecord envelopes,
  so the field is not an OTel attribute — it is the line's emit
  time.
- The pin is mostly conservative: HTTP semconv reached Stable in
  v1.23.0 and the attributes this project adopts sit inside that
  stable surface. One exception worth flagging: in v1.40.0 the
  `http.server.active_requests` metric still carries the Development
  stability badge (only `http.server.request.duration` is Stable),
  so #26 must accept that the metric's name or shape may change
  before it stabilises. The ADR is renewed if that rename lands.

## Follow-ups

- [#26](https://github.com/aidanns/agent-auth/issues/26) — metrics
  endpoint implementation, must use the names pinned here.
- [#20](https://github.com/aidanns/agent-auth/issues/20) — audit log
  schema pinning, must adopt semconv HTTP attribute keys.
- [#33](https://github.com/aidanns/agent-auth/issues/33) —
  observability design document, builds on this ADR.
