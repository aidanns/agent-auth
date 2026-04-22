<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0023 — Deepen `/things-bridge/health` to verify the Things-client binary is resolvable

## Status

Accepted — 2026-04-21.

## Context

`GET /things-bridge/health` was introduced alongside the Docker Compose
readiness probe and originally returned `200 {"status":"ok"}`
unconditionally after authenticating the probe token. That is enough
for container orchestrators to tell the process is listening, but it is
weaker than the `.claude/instructions/service-design.md` standard, which
requires a health endpoint to return 200 **only when critical
subsystems are healthy**.

The bridge has two critical downstream dependencies:

1. **`things_client_command`** — the CLI subprocess the bridge spawns
   per request to translate HTTP operations into AppleScript /
   fixtures. If that executable is not on PATH (misconfiguration, image
   shipped without the CLI, stale volume mount), every Things request
   fails with `ThingsError: things client not found`. The bridge
   currently reports healthy anyway.
2. **`auth_url`** — agent-auth's HTTP address. If that is unreachable
   the bridge cannot authorise any request, including the probe itself.

Issue [#91](https://github.com/aidanns/agent-auth/issues/91) calls out
the gap and suggests a "cheap liveness deepening" as the fix.

## Decision

Add a single additional check to `_handle_health` before the 200
response: resolve `things_client_command[0]` and return
`503 {"status":"unhealthy"}` if resolution fails.

Implementation details:

- A `_HealthChecker` on the server wraps `shutil.which(cmd)` with a
  30-second in-memory cache keyed on the first element of the
  configured command. The cache is warm enough that a 1-second probe
  cadence pays at most one filesystem walk per window, but cold enough
  that a freshly-installed binary shows up within one window without a
  server restart.
- The 503 body mirrors the agent-auth pattern
  (`{"status": "unhealthy"}` — not an error code). This keeps the
  readiness body shape uniform across services. Error-code table in
  `design/error-codes.md` documents the body explicitly.
- `auth_url` reachability is **not** re-probed. The bridge already
  issues a `POST /agent-auth/v1/validate` to authorise the probe
  token; if agent-auth is down the /health call surfaces a 502
  `authz_unavailable`. Adding a second ping would just duplicate that
  signal and add a code path that is hard to distinguish from the
  primary authz call.

## Considered alternatives

### Ping a dedicated agent-auth liveness endpoint from inside /health

A second HTTP call from the bridge to agent-auth's own `/health` inside
our handler.

**Rejected** because:

- The primary authz call already proves reachability; the second call
  exists only to surface a 503 instead of a 502 when agent-auth is
  down, which is a cosmetic distinction.
- It changes the /health call from one outbound HTTP request into two,
  doubling the failure surface of a probe that is supposed to be
  cheap.

### Execute the Things client CLI with a `--version` probe

Invoke the configured `things_client_command[0] --version` (or an
equivalent no-op sub-command) on every probe to confirm not just PATH
resolution but also that the binary can run.

**Rejected** because:

- On macOS the real CLI requires osascript access which pops a TCC
  prompt if permissions lapse; we don't want /health to trigger user
  prompts.
- It is far from "cheap". A subprocess spawn per probe is orders of
  magnitude more expensive than a cached PATH lookup.
- The PATH-resolvability check catches the dominant failure mode (CLI
  not deployed / wrong command configured). A deeper check belongs on
  a slower, higher-privileged diagnostic endpoint if it becomes
  necessary.

### Expose a separate `/ready` endpoint for the deeper check

Keep `/health` as the unconditional liveness probe and add a second
`/ready` endpoint for readiness.

**Rejected** because:

- The project's standard (`.claude/instructions/service-design.md`
  §HTTP services) has a single "health" endpoint that means
  "200 when critical subsystems are healthy" — no kubernetes-style
  liveness/readiness split.
- Adding a second endpoint would also require scope design, audit
  wiring, and a new error-codes row; deepening the existing endpoint
  costs none of that.

## Consequences

**Positive**:

- Health probes now fail closed when the bridge's per-request
  dependency is missing, matching the service-design standard.
- The 30-second resolver cache keeps the probe latency under a
  microsecond in steady state, so Compose healthcheck cadence is
  unchanged.
- The 502 (authz down) vs 503 (things-client missing) split gives
  operators a direct signal about which dependency failed.

**Negative / accepted trade-offs**:

- The cache means a binary removed mid-operation will keep reporting
  healthy for up to 30 seconds. This is acceptable for a probe; any
  longer-horizon monitoring belongs in alert rules over the Prometheus
  metrics, not in the readiness probe.
- `_HealthChecker` introduces a new server-side state object with its
  own lifecycle. It has no cleanup requirements, so the extra
  complexity is minimal.

## Follow-ups

None. A richer check (config-file validation, subprocess exec probe,
dedicated agent-auth ping) can be layered on later behind a new scope
if operational evidence demands it, but there is no tracked follow-up
from 1.0.
