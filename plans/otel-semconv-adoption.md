# Plan: Adopt OpenTelemetry semantic conventions for metrics and logs

Issue: [#118](https://github.com/aidanns/agent-auth/issues/118).

Source standard: `.claude/instructions/service-design.md` —
*Observability design*.

## Goal

Commit the project to the [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
so that future observability work (#26 Prometheus metrics, #20 audit
log schema pinning, #33 observability design document) emits telemetry
operators can read without project-specific adapters.

The decision is forward-looking: the metrics endpoint does not exist
yet, and the audit log schema is not yet contract-tested. #118 lands
the standards choice and the mapping; #26, #20, and #33 implement
against it.

## Non-goals

- Implementing `GET /agent-auth/metrics` or `GET /things-bridge/metrics`.
  That is #26.
- Rewriting existing audit log events to new field names. The existing
  audit schema uses domain terms (`event`, `family_id`, `token_id`,
  `tier`, `grant_type`, `scope`, `reason`, `scopes`) that have no OTel
  equivalent; they remain as-is. HTTP-attribute fields are not emitted
  today — #20 (audit log schema pinning) introduces them using the
  semconv keys this plan pins.
- Updating `design/functional_decomposition.yaml` and
  `design/product_breakdown.yaml` with a new "Observability /
  Telemetry" leaf. The decomposition describes the system's functions
  and components that *exist*; the metrics endpoint (#26) and the
  schema-pinned audit log (#20) do not exist yet, so their
  decomposition entries land with those issues, not this one. The
  existing `Audit Logging` leaf continues to describe the present-day
  audit log and is not renamed.
- Instrumenting via the OpenTelemetry SDK. The project emits Prometheus
  text and JSON-lines logs directly; we adopt the *attribute-naming
  conventions*, not the wire protocol or SDK.
- Producing the full observability design document. That is #33;
  this plan delivers only the OTel semconv reference that document
  will build on.

## Deliverables

1. **ADR `design/decisions/0015-opentelemetry-semantic-conventions.md`**
   — commits to OTel semconv as the naming source for HTTP-server
   metrics and HTTP-attribute log fields, pins a specific version
   (`v1.40.0`, released 2026-02-19 — the latest stable at the time
   of adoption), and enumerates the current deviations and
   domain-specific extensions with rationale.
2. **`design/DESIGN.md` — new `## Observability` section** — short
   section summarising:
   - the decision to follow OTel semconv with a link to the ADR,
   - the specific attribute names we adopt for HTTP server signals
     (method, route, status code, scheme, peer address, service
     identity),
   - metric-naming conventions for HTTP server duration and active
     requests,
   - the list of audit-log fields that remain domain-specific
     (with rationale — they describe authorization decisions, not
     HTTP mechanics),
   - pointers forward to #26/#20/#33 for the work that implements
     against this mapping.
3. **`design/decisions/README.md` index entry** for the new ADR.
4. **Plan file** in `plans/otel-semconv-adoption.md` (this file).

## Mapping (authoritative reference)

### HTTP server metrics (applies to #26)

Per OTel semconv `metrics/http.md` v1.40.0:

- `http.server.request.duration` (histogram, seconds) — per-endpoint
  latency. Attributes: `http.request.method`, `http.route`,
  `http.response.status_code`, `url.scheme`, `error.type` (when the
  response is an error).
- `http.server.active_requests` (UpDownCounter; gauge in Prometheus)
  — in-flight requests. Attributes: `http.request.method`,
  `url.scheme` (required); `server.address`, `server.port` (opt-in).

Domain-specific counters (no OTel equivalent; keep current
project-namespaced names):

- `agent_auth_validations_total{result, reason, tier}` — validation
  outcomes from `POST /agent-auth/validate`.
- `agent_auth_token_operations_total{operation}` — `created`,
  `refreshed`, `reissued`, `revoked`, `modified`.
- `agent_auth_approvals_total{outcome, grant_type}` — JIT approval
  outcomes.

Prometheus exposition uses `_` instead of `.`, so `http.server.request.duration`
is exposed as `http_server_request_duration_seconds` (Prometheus
convention). Attribute keys become label names with the same
substitution (`http_request_method`, `http_response_status_code`).

### Audit log — HTTP attributes (applies to #20)

When the audit log captures HTTP request metadata, use OTel attribute
keys:

- `http.request.method` (string) — e.g. `POST`.
- `http.route` (string) — templated path (low cardinality), e.g.
  `/agent-auth/token/modify`.
- `url.path` (string) — actual path with concrete IDs
  (forensics-useful).
- `http.response.status_code` (int).
- `url.scheme` (string) — `http` or `https`.
- `client.address` (string) — remote peer IP.
- `user_agent.original` (string) — verbatim `User-Agent` header.
- `network.protocol.version` (string) — e.g. `1.1` or `2`.
- `server.address` / `server.port` — local bind address.
- `service.name` (string) — `agent-auth` or `things-bridge`.
- `service.version` (string) — the release version (PEP 440).

### Audit log — domain-specific fields (kept, not covered by OTel)

These describe authorization state, not HTTP mechanics, and stay on
domain names because no OTel equivalent exists:

- `event` — discriminator (`validation_allowed`, `validation_denied`,
  `token_created`, `token_refreshed`, `token_reissued`,
  `token_revoked`, `scopes_modified`, `reissue_denied`).
- `token_id`, `family_id` — opaque identifiers.
- `scope` — the requested scope string.
- `scopes` — list of scopes on a family.
- `tier` — `allow` | `prompt` | `deny`.
- `grant_type` — JIT grant flavour (e.g. `one_time`, `until`).
- `reason` — denial reason code.
- `timestamp` — ISO 8601 UTC (OTel uses `Timestamp` on the LogRecord
  envelope in the wire protocol, but we emit JSON-lines and keep
  `timestamp` as a JSON key).

### Deviations from OTel semconv

Documented in the ADR:

1. Prometheus exposition replaces `.` with `_` in metric and label
   names. This is the Prometheus convention, not a project choice.
2. `timestamp` (not `Timestamp`) is the JSON key for the log emit
   time — we emit flat JSON objects, not OTel LogRecord envelopes.
3. Audit-domain fields listed above have no semconv equivalent and
   keep their existing names.

## Verification

- Changes are documentation only. No source code or tests change.
- `scripts/verify-standards.sh` gains no new gate from this plan.
  The "observability doc references the OTel semconv version"
  acceptance criterion is satisfied by the new ADR + DESIGN.md
  section, both of which are grep-checkable; formal regression
  coverage arrives with #33 (which will assert the observability
  doc contains the required sections — including the semconv
  version reference).

## Standards review (per `plan-template.md`)

- **Design verification** — after writing, diff the DESIGN.md section
  against the ADR to ensure they agree on the mapping. The
  `design.md` "Keeping design docs current" step also requires
  reviewing `design/functional_decomposition.yaml` and
  `design/product_breakdown.yaml`. No new function or component is
  introduced by this plan (the metrics endpoint and schema-pinned
  audit log ship with #26 / #20), so no YAML entries are added
  here; the existing `Audit Logging` entries remain accurate.
- **Threat model** — no security-relevant code change; no
  `SECURITY.md` update.
- **ADRs** — one new ADR (0015), indexed.
- **Cybersecurity standard** — n/a (documentation only).
- **QM/SIL** — the ADR is an approved design decision; no
  additional evidence required.
- **Coding / service-design / testing / tooling standards** — no
  code or test changes, so no review needed beyond the
  observability-standards check in `service-design.md`, which this
  plan is the response to.
- **Release and hygiene** — `CHANGELOG.md` gets an entry under the
  unreleased section for the ADR and observability design
  commitments.

## Follow-ups (tracked elsewhere)

- [#26](https://github.com/aidanns/agent-auth/issues/26) — metrics
  endpoint implementation, must use the names in this plan.
- [#20](https://github.com/aidanns/agent-auth/issues/20) — audit log
  schema pinning, must introduce HTTP-attribute fields per this
  plan when it adds them (no HTTP-attribute fields are emitted
  today, so there is nothing to rename).
- [#33](https://github.com/aidanns/agent-auth/issues/33) —
  observability design document, supersedes the DESIGN.md summary
  added here by folding it into a dedicated doc.
