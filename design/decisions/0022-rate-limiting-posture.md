<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
SPDX-License-Identifier: MIT
-->

# ADR 0022 — Defer application-layer rate limiting; rely on loopback-only bind and bounded request bodies

## Status

Superseded by [ADR 0027](0027-rate-limiting-implementation.md) — 2026-04-23.

The deferral posture here held up until TLS landed for the
devcontainer-to-host path (ADR 0025). With the trust boundary now
allowed to extend beyond loopback, the "we're loopback-only"
argument no longer applies, and the disk-growth vector called out by
#102 (rapid token creation from a compromised caller) needed a
concrete ceiling. ADR 0027 carries the implemented posture; the
`rate_limit_per_minute: 0` opt-out keeps the original deferral
option available for deployments that still match this ADR's
assumptions.

Accepted — 2026-04-21.

## Context

Issue [#30](https://github.com/aidanns/agent-auth/issues/30).
`.claude/instructions/service-design.md` calls for an expected
request-rate budget per endpoint and either an implemented rate
limit or a documented rationale for deferring it. Today neither
server applies application-layer rate limiting; the only DoS guard
on the request path is the 1 MiB body cap enforced in
`AgentAuthHandler._read_json` (and the read path is GET-only on
things-bridge, which trivially bounds body size).

The services' trust boundary is a single host: both bind to
`127.0.0.1` by default, accept traffic only from local processes,
and the `agent-auth:manage` surface requires a bearer token issued
and stored in the system keyring on the same machine. There is no
public-network deployment model and no multi-tenant posture — the
threat model in `SECURITY.md` names the user themselves as the
single principal.

Under those constraints, rate limiting protects the service from
two realistic adversaries:

- **Buggy local agent.** A looping caller could burn CPU and flood
  the audit log. The typical symptom is a validation-storm on
  `POST /agent-auth/v1/validate` from a runaway automation script.
- **Compromised local process.** A process that has already
  escalated on the host could amplify its blast radius by
  exhausting the approval-prompt queue for a sensitive scope. This
  matters more for the things-bridge surface (Things AppleScript
  is user-visible and throttled by the OS automation pipeline
  anyway) than for agent-auth itself.

It is *not* plausibly useful against:

- Remote network floods — the loopback bind excludes them entirely.
- Credential stuffing — tokens are HMAC-signed opaque identifiers;
  an attacker without the signing key cannot mint valid tokens no
  matter the request rate.

## Considered alternatives

### Per-IP / per-token token-bucket on every endpoint

Standard web-app rate limit — N requests per token-bucket refill
per peer identity (IP, or bearer token id).

**Rejected** because:

- Peer identity at `127.0.0.1` is effectively one value. Per-IP
  limits do not distinguish concurrent agents on the same host;
  per-token limits bucket the management path and the agent-
  validation path against each other, which is the opposite of
  what the threat model asks for.
- The buggy-agent case is better solved by the audit log and
  metrics: `agent_auth_validation_outcomes_total{outcome="denied"}`
  spikes on a loop and the operator notices. A hard cap adds a new
  failure mode (legitimate burst > cap → refusal) without
  preventing the observable loop.
- Every token family would need a bucket state. Sizing and
  persisting that state is new complexity on the storage tier,
  which agent-auth keeps deliberately tight.

### JIT-approval concurrency limit only

Narrower variant: cap the number of in-flight `prompt`-tier
approvals per family so a compromised caller cannot queue an
unbounded number of system-modal dialogs.

**Rejected for this ADR** because the existing `ApprovalManager`
already serialises approval requests per family through the
notification plugin's own blocking semantics (the plugin returns
before the next request is dispatched), which bounds the queue
depth to effectively 1 per family. A separate counter is redundant
here. If a future plugin implementation runs approvals concurrently
across families, we will revisit.

### Reverse-proxy rate limit

Run `agent-auth` and `things-bridge` behind a local reverse proxy
(nginx, envoy, caddy) with rate-limit directives.

**Rejected** because it adds an operator-visible component for a
single-user deployment and cannot see past the 127.0.0.1 bind —
every request would hit it from `localhost` so it would only
provide global, not per-caller, limits. Moving that cap into the
service itself is cheaper if we later decide it is needed.

## Decision

**Defer application-layer rate limiting.** The 1.0 release ships
without per-IP or per-token buckets.

Keep these guards instead:

- Loopback-only bind (`127.0.0.1`) remains the default in
  `Config.host` on both services. Remote-binding is deliberately
  an operator opt-in, not a packaging default.
- `AgentAuthHandler.MAX_BODY_SIZE = 1 MiB` bounds the validation
  and token-management request bodies. A caller cannot blow RAM
  by sending a huge JSON payload.
- `ThingsBridgeHandler._safe_id` caps path-segment length at
  128 bytes, so id-carrying paths cannot defeat metric-label
  templating.
- `ApprovalManager` serialises JIT approvals per family — if a
  plugin blocks on the user, the family cannot enqueue a second
  prompt until the first resolves.
- `agent_auth_validation_outcomes_total` on `/metrics` gives the
  operator a runaway-loop signal without forcing refusal.

Document the decision and the expected-rate ceiling in
`design/DESIGN.md` "Rate limiting and request budgets" so a
future threat-model refresh can recheck the assumption.

## Consequences

Positive:

- No new state on the storage tier. Token-store schema stays at
  the shape pinned by #20 + the migration story in #29.
- No rejection path for legitimate bursts. A script driving the
  CLI at normal agent pace will never trip an artificial cap.
- Metric signal (`agent_auth_validation_outcomes_total`) and the
  audit log together cover the diagnostic need rate limits are
  usually built to serve.

Negative / accepted risks:

- A buggy local agent can still produce a tight validation loop.
  The operator diagnoses via `/metrics` + audit log and kills the
  agent; the service does not throttle automatically.
- If a future deployment exposes either server beyond `127.0.0.1`
  (reverse proxy, devcontainer port-forward, remote operator
  tooling), the decision recorded here no longer applies and must
  be revisited. The follow-up trigger is "trust boundary moves
  off-host", not "more requests per second".
- JIT-approval storms from a compromised peer rely on the
  notification plugin being slow-serial; moving to a batched or
  concurrent plugin will require reopening this ADR.

## Follow-ups

- If/when the trust boundary extends beyond localhost (e.g.
  devcontainer port-forward surfaces a user-visible listener),
  reopen this ADR and implement per-peer token-bucket limiting
  with a corresponding `agent_auth_requests_throttled_total`
  counter.
- Reopen this ADR when the notification plugin migrates to the
  out-of-process HTTP model in issue #6 — the per-family
  concurrency bound rests on the current in-process plugin
  contract.
