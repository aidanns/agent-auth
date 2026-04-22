<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0024 — Single-source audit trail at agent-auth with a cross-service resource envelope

## Status

Accepted — 2026-04-22.

## Context

Issue [#100](https://github.com/aidanns/agent-auth/issues/100) asks for
a consolidated, structured audit-log schema across every service so a
SIEM can ingest the whole system with a single parser.

The current state on main:

- `agent_auth.audit.AuditLogger` already writes JSON-lines with a
  pinned `schema_version`, a discriminator `event`, and an ISO 8601
  `timestamp` (`src/agent_auth/audit.py`).
- `tests/test_audit_schema.py` contract-tests every documented event
  kind; `scripts/verify-standards.sh` gates presence of that test file.
- things-bridge emits **no audit log at all**. ADR 0017 and
  `design/DESIGN.md` §Log streams commit to routing every bridge
  request's authorization trace through agent-auth's `POST /validate`,
  which agent-auth audits.

Two gaps remain against #100's acceptance:

1. **No emitter identity on entries.** `design/DESIGN.md` claims
   `service.name` / `service.version` are included on every line, but
   the code never emits them. A consumer joining multiple audit
   sources (current log + a retained archive from a renamed file)
   has to infer the emitter from path conventions.
2. **Drifted HTTP-attribute documentation.** The same DESIGN.md
   section lists OTel HTTP request attributes
   (`http.request.method`, `http.route`, `url.path`, …) as "populated
   on events that originated from an HTTP request", but the code never
   attaches them to any entry today.

## Considered alternatives

### Add a parallel audit log to things-bridge

Stand up a second `AuditLogger` inside things-bridge (its own
`audit.log` path, its own events) and emit the same schema.

**Rejected** because:

- Every authorization decision a bridge request triggers is already
  captured by agent-auth as a `validation_allowed` /
  `validation_denied` entry. A bridge-side emit would be a strict
  duplicate with a small time skew.
- Two audit writers means two schema-emit contracts, two retention
  paths, and two sources that must be kept in sync when the schema
  evolves. That's exactly the thing SIEMs find hard to ingest — which
  is the problem #100 set out to fix.
- There is no bridge-only event today that isn't expressible through
  `things-bridge:*` scope checks on agent-auth.

### Drop the HTTP-attribute table from DESIGN.md entirely

Remove the HTTP-attribute table on the grounds that it documents
fields the code doesn't emit.

**Rejected** because:

- ADR 0017 (OTel semconv adoption) explicitly names those attribute
  keys as the canonical naming source for when they are emitted.
  Dropping the table deletes the naming contract and invites future
  contributors to reinvent names inconsistently.
- A "reserved / not emitted today" label costs little and keeps
  future work anchored to semconv.

### Emit HTTP attributes now as part of this ADR

Thread an HTTP request context through every `audit.log_*` call site
so authorization-decision entries carry the full semconv HTTP
attribute set.

**Rejected** because:

- `AuditLogger` currently has no request context; every call site
  would need to pass one, and CLI-triggered token operations
  (`agent-auth token revoke`) have no HTTP context at all, so the
  code would need to carry a nullable context type everywhere.
- That's a larger surface-area change than #100 targets — and it
  touches the audit emit sites mutation-tested under the security
  ratchet (ADR 0021), expanding review blast radius.
- The naming contract is already pinned (see previous alternative),
  so a later issue can add emission without renegotiating keys.

## Decision

1. **Keep the audit trail single-sourced at agent-auth.**
   things-bridge continues to emit no audit log. Document the
   rationale in `design/DESIGN.md` §Log streams.
2. **Extend `AuditLogger` to emit OTel resource attributes on every
   entry.** Add `service.name = "agent-auth"` (constant today) and
   `service.version = agent_auth.__version__` to the fixed envelope
   in `AuditLogger.log()`. This is a non-breaking schema addition
   per the stability policy ("adding a new optional field is
   non-breaking; version stays the same"), so `SCHEMA_VERSION` stays
   at `1`.
3. **Pin the resource fields as part of the contract.** Every test
   in `tests/test_audit_schema.py` already asserts base fields via
   `_assert_base_fields`; extend that helper to assert `service.name`
   is `"agent-auth"` and `service.version` is a non-empty string on
   every entry. Add a dedicated regression test that writes two
   different kinds of event and asserts the resource envelope is
   present on both.
4. **Mark HTTP attributes as reserved.** Relabel the DESIGN.md HTTP
   attribute table as *"Reserved for future events that originate
   from an HTTP request. Not emitted today."* A future issue may
   promote individual fields to emitted status, case by case, without
   needing to rename them.

## Consequences

**Positive**:

- SIEM filter expressions can rely on `service.name` being present
  with exactly that dotted key on every line — no need to special-case
  the emitter or infer it from the file path.
- The envelope is future-proof: a second audit emitter in the
  project would slot in under the same contract with zero schema
  churn.
- DESIGN.md now matches the code — no more drift between a documented
  attribute table and its emission status.

**Negative / accepted trade-offs**:

- `service.name` is redundant today (only one emitter). That's the
  cost of reserving the envelope shape before it's strictly needed.
- The `service.version` value depends on package metadata. In a
  source-checkout execution (rare outside tests), it falls back to
  `0.0.0+unknown` — acceptable because such runs are not operator-
  facing.

## Follow-ups

- **HTTP-attribute emission** — no issue filed yet; track under a
  new issue only if SIEM requirements demand the per-request HTTP
  context on authorization-decision entries. Naming is pre-pinned
  via ADR 0017 and the DESIGN.md reservation, so emission can land
  without a renaming negotiation.
- Dead `log_path` field in `things_bridge/config.py` (never read by
  the bridge) predates the single-source audit decision; cleanup is
  out of scope here but worth a follow-up if the config surface is
  refactored.
