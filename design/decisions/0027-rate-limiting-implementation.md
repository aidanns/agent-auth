<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0027 — In-memory per-token-family rate limiting

## Status

Accepted — 2026-04-23. Supersedes [ADR 0022](0022-rate-limiting-posture.md).

## Context

ADR 0022 deferred application-layer rate limiting on the grounds
that both services bind `127.0.0.1` and run single-user on one host,
so the DoS threat was effectively limited to a compromised local
process. Two things changed since:

1. **ADR 0025 landed an optional TLS listener** for the
   devcontainer-to-host path. The trust boundary can now extend
   beyond loopback to any workload running inside a sibling
   container on the same host network, which is precisely the
   "trust boundary extends beyond localhost" trigger ADR 0022
   named as its follow-up condition.
2. **Issue [#102](https://github.com/aidanns/agent-auth/issues/102)**
   explicitly called out the DB-growth vector: a compromised
   management caller can pound `POST /agent-auth/v1/token/create`
   and bloat `tokens.db` without bound. ADR 0022's reliance on the
   1 MiB body cap and `ApprovalManager` serialisation does not
   address that path — token creation is a small JSON body that
   happily completes many times a second.

The existing mitigations (loopback default, 1 MiB body cap,
approval serialisation) stay in place; this ADR adds a
per-family ceiling on top.

## Considered alternatives

### Per-source-IP buckets keyed on `client.address`

Rate-limit on the TCP peer address rather than the token family.

**Rejected** because:

- Loopback is the common case, so every client arrives from
  `127.0.0.1` and shares a single bucket — which immediately
  collapses into a global rate limit. That's not useful for
  separating a misbehaving agent from a cooperating one.
- Agents-in-devcontainers also tend to share a single bridge-
  network address, so the IP key would collapse across callers
  there too.
- Token-family identity is the actually-meaningful unit of work
  because every call already authenticates a family — no extra
  moving parts needed.

### Persistent bucket state (SQLite-backed)

Survive restarts so a hammering caller that crashes the server
cannot just come back and drain a fresh bucket.

**Rejected** because:

- Writes on the hot validate path are exactly what the persistence
  would be, and the performance budget (ADR's perf work, #41)
  is tight. An extra per-request SQLite write would be a
  regression.
- Restart recovery already implies the operator is in the loop
  (process supervisor spawning the service), so the "free bucket
  on restart" attack is observable out-of-band — it's not the
  threat model this limiter is trying to defeat.

### Distributed rate limiter (Redis / external cache)

Share bucket state across a multi-process agent-auth deployment.

**Rejected** because:

- The project is a single-user, single-process deployment today
  (`ApprovalManager` serialisation assumes one process; see ADR
  0022). No multi-process support is planned before 1.0.
- A Redis dependency would drag an operational prerequisite into
  a tool that installs with `pip install`.

### Exempt `/health` and `/metrics` from the bucket

Operational endpoints often need a high-cadence probe from a
container orchestrator.

**Rejected** because:

- The user directive for this ADR was "gating all endpoints."
- A liberal default (`rate_limit_per_minute: 600`, = 10/s) is
  plenty of headroom for a 1-second-interval Docker healthcheck
  plus normal workload.
- Exempting would have required carving out a scope-based
  special case in the dispatch layer, which would be easy to
  drift from on a future refactor.

## Decision

1. **Token-bucket per `family_id`, in process memory.**
   `src/agent_auth/rate_limit.py` carries the implementation.
   Capacity equals the per-minute rate (so the first minute of a
   fresh family bursts at the sustained rate), refill is
   `rate / 60.0` tokens per second, and state lives in a
   `dict[str, _Bucket]` guarded by a single `threading.Lock`.
2. **Buckets only exist for verified families.** Every handler
   resolves the bearer token to a non-revoked family before
   consulting the limiter. Unknown `family_id` values therefore
   cannot inflate the map by probing.
3. **Idle eviction at 300 seconds** bounds memory to the actively-
   used families — no eviction thread, sweeps run opportunistically
   under the map lock on the next `consume`.
4. **Every authenticated endpoint consumes one token.** That is:
   `/validate`, `/token/refresh`, `/token/reissue`,
   `/token/status`, `/token/create`, `/token/list`,
   `/token/modify`, `/token/revoke`, `/token/rotate`, `/health`,
   `/metrics`. Unauthenticated or mis-authenticated requests are
   rejected before the bucket is touched.
5. **Denial surface**: the server returns `429 {"error": "rate_limited"}`
   with a `Retry-After` header carrying integer seconds
   (per RFC 7231 §7.1.3). A `rate_limited` audit entry is
   written with `family_id` and (where applicable) `scope`.
   `agent_auth_validation_outcomes_total{outcome="denied",reason="rate_limited"}`
   increments.
6. **Config**: `rate_limit_per_minute: int = 600`. A value of `0`
   disables the limiter entirely, preserving the deferred
   posture from ADR 0022 for deployments that still want it.
   Any negative value is a config error.
7. **things-bridge forwarding**: `AgentAuthClient` maps 429 to
   a new `AuthzRateLimitedError` carrying the upstream
   `Retry-After`. The bridge server emits a matching 429 with
   that header verbatim, so clients pace themselves against
   agent-auth's bucket rather than a second one. things-cli
   raises `BridgeRateLimitedError`, which the CLI maps to
   exit-code 6 with a user-facing "retry after N seconds" message.

## Consequences

**Positive**:

- Closes the #102 disk-growth vector: a compromised management
  caller can create at most `rate_limit_per_minute` token
  families per minute, so DB growth is bounded by config, not
  by the attacker's CPU.
- Per-family isolation — a noisy automation consuming the bridge
  does not rate-limit other token families on the same host.
- Operational endpoints remain uniformly gated; the same pattern
  applies across the whole surface so a new endpoint picks up
  rate-limiting from `_require_management_auth` /
  `_authenticate_bearer_scope` automatically.

**Negative / accepted trade-offs**:

- State is per-process and ephemeral. Restart resets all buckets.
  This matters only if an attacker can force server restarts,
  which already implies they are the local operator.
- A Docker healthcheck running at high cadence will consume the
  health family's bucket over time; operators running aggressive
  probes need to raise `rate_limit_per_minute` or relax the
  probe cadence. Default of 600/min fits 1/s probes with headroom.
- Bucket eviction is opportunistic, so a family that goes idle
  mid-sweep may keep memory for up to
  `_BUCKET_IDLE_EVICTION_SECONDS` past its last activity. That's
  acceptable for the expected usage scale (tens of families).

## Follow-ups

- A future ADR may revisit persistent bucket state once #6
  (out-of-process notification plugin) lands, since multi-process
  agent-auth becomes plausible at that point.
- Optional burst capacity distinct from sustained rate could be
  added if an operator needs long-horizon averaging; not shipped
  for 1.0.
- No separate issue filed for the `/health` and `/metrics`
  exemption discussion — the liberal default + operator-tunable
  rate should cover the observed cases.
