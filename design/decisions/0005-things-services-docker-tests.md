<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0005 — Per-service Docker integration tests for the things-\* surface

## Status

Accepted — 2026-04-19.

## Context

ADR `0004-docker-integration-tests.md` migrated `agent-auth`'s HTTP
integration tests onto a per-test Compose pattern (one
`testcontainers.compose.DockerCompose` project per test, ephemeral
loopback port, bind-mounted `config.yaml`). The remaining services in
this repo —
`things-bridge`, `things-cli`, and `things-client-cli-applescript` —
still ran in-process, sharing host SQLite/keyring state and using
private fakes (`FakeAuthz`, `_InjectableThings`, the dual-handler fake
HTTP servers in `test_things_cli_client.py`). The same host-port /
shared-state collision risk applied, and the in-process suites bypassed
the compose / CLI / config wiring entirely. Tracked as
[#78](https://github.com/aidanns/agent-auth/issues/78).

## Considered alternatives

### Continue with in-process threaded servers

Keep the existing `ThreadingHTTPServer`-on-`127.0.0.1:0` pattern; rely
on test-runner parallelism limits to avoid collisions.

**Rejected** for the same reasons spelled out in ADR 0004 — a
kernel-assigned port doesn't isolate the SQLite database, the keyring,
the audit log, or the fake-client subprocess working dir. The deeper
problem is that the in-process suite never exercises the real CLI →
config → server wiring, so contract drift between any two of
`agent-auth` / `things-bridge` / `things-cli` is invisible.

### One Compose project per service, separate Dockerfiles

Build a dedicated `Dockerfile.test.things-bridge` (and so on) per
service.

**Rejected.** All four CLIs ship from the same `pyproject.toml` and are
installed by the same `pip install .`. Splitting Dockerfiles
duplicates the install layer with no isolation gain — one image with
per-service Compose `entrypoint` overrides is strictly less wiring.

### Single Compose project per session reused across tests

Stand up one stack at session start, reuse across tests.

**Rejected.** Token state, scope state, and Things fixtures are
test-specific. A shared stack forces every test to scrub state on
entry/exit, which is exactly the failure mode that motivated the
per-test isolation in ADR 0004.

## Decision

Extend the per-test Compose pattern to the things services, sharing one
test image across all of them:

- **One image (`docker/Dockerfile.test`) for every service.** It
  installs the working-tree wheel, which provides every console-script
  entry point. Each Compose service overrides `entrypoint`/`command` to
  pick which CLI to run. The Dockerfile additionally copies
  `tests/things_client_fake/` to `/opt/tests-support/` so the bridge
  can `python -m tests.things_client_fake` for its Things backend
  without an installed distribution. The exclusion of both
  `tests_support` and the `tests/` tree from the production wheel keeps
  the test-only modules out of any shipped artefact.
- **Single shared Compose file at `docker/docker-compose.yaml`.** It
  declares the `agent-auth` + `things-bridge` pair on an internal
  Compose network; both services publish loopback-only host ports. The
  bridge's runtime config ships inline via a Compose `configs:` block
  rather than a bind-mounted file, so the compose file is the single
  source of truth for the integration topology *and* the bridge's
  baseline config. Every per-service fixture spins this same file up
  under a per-test UUID Compose project — the agent-auth-only fixture
  also starts the bridge (with an empty fixtures dir bind-mounted in)
  so the topology is identical regardless of which service the test
  drives. The ~1 s of extra container time per agent-auth test is the
  cost of one source of truth for the integration topology.
- **Per-service `tests/integration/<service>/conftest.py`.** Each
  fixture mints a per-test UUID Compose project, writes config and
  Things fixtures into per-test bind-mount dirs, and yields a service
  handle (`ThingsBridgeStack`, `ThingsCliInvoker`) that exposes the
  HTTP base URL plus typed helpers for token creation.
- **`things-cli` integration tests run inside the bridge container**
  via `docker compose exec things-bridge things-cli …`. Credentials
  persist to a per-test path inside the container so the 0600
  credential-file enforcement runs against the container's own
  filesystem (no UID-mismatch on host bind mounts).
- **`things-client-cli-applescript` Linux contract tests run the fake
  CLI via `docker run --rm`.** A Compose project would be overkill for
  a one-shot stdin/stdout subprocess. The AppleScript-specific
  behaviour stays under the existing Darwin-gated suite — Linux only
  pins the wire protocol that `things-bridge` consumes.
- **Add `GET /things-bridge/health`.** Authenticated under a
  `things-bridge:health` scope, mirroring the agent-auth health
  endpoint pattern. The Compose readiness probe treats 401 (no token)
  as a positive "server is up" signal — same indirection used for
  `/agent-auth/health`.
- **Retired in-process suites:**
  - `tests/test_things_bridge_e2e.py` — happy-path and authz-shape
    coverage moved to `tests/integration/things_bridge/test_bridge.py`;
    token-expiry and authz-unavailable edge cases continue to be
    covered by `tests/test_things_bridge_server.py` at the unit layer
    (`test_get_todos_token_expired_maps_to_401`,
    `test_get_todos_authz_unavailable_maps_to_502`), which is the
    cheaper place to exercise pure error-mapping.
  - `tests/test_things_client_cli_contract.py` — fully replaced by
    `tests/integration/things_client_applescript/test_contract.py`.
  - `tests/test_things_bridge_server.py`,
    `tests/test_things_bridge_authz.py`, and
    `tests/test_things_cli_client.py` are kept as in-process unit
    tests — they exercise routing, error mapping, and refresh/reissue
    decision logic that the integration layer does not duplicate.
- **`scripts/verify-integration-isolation.sh` extended.** It now
  rejects raw loopback literals across every per-service subdirectory
  and requires each per-service `conftest.py` to reference either
  `docker/docker-compose.yaml`, a `docker/compose.test.*.yaml` file, or
  a `docker run` invocation. The build-call check accepts either the
  top-level conftest or the new `tests/integration/_support.py` helper
  module.

## Consequences

- Integration runs cost one image build per session (cached layers
  amortise across services) and one per-test Compose start. Per-service
  Compose projects with two services (`agent-auth` + `things-bridge`)
  start in roughly 1–2 s on Linux; CI gates integration after the unit
  layer passes so the slower step only runs against likely-good code.
- The Linux contract test for `things-client-cli-applescript` does not
  cover AppleScript-specific behaviour. The macOS-gated suite in
  `tests/test_things_client_applescript_things.py` continues to own
  AppleScript correctness; a follow-up macOS GitHub-hosted runner
  workflow is planned for the executable end of that path.
- The shared test image carries `tests/things_client_fake/` in
  `/opt/tests-support/`. Same plugin-trust caveat as `tests_support`
  ([#6](https://github.com/aidanns/agent-auth/issues/6)) — acceptable
  here because the package is excluded from the wheel and is only on
  `PYTHONPATH` inside the test image.

## Follow-ups

- Container-scope tuning: if integration wall-clock becomes a problem,
  switch the bridge factory to a session-scoped Compose project with
  per-test config overrides written to a sub-path. Same knob discussed
  in ADR 0004.
- macOS GitHub-hosted runner workflow that exercises the real
  AppleScript CLI against a stub Things 3 fixture (separate from this
  ADR; tracked alongside the ongoing JIT-approval out-of-process
  migration in #6).
