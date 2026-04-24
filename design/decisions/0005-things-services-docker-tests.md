<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0005 — Per-service Docker integration tests for the things-\* surface

## Status

Accepted — 2026-04-19. Amended 2026-04-23 (see *Amendment — 2026-04-23*
below). ADR 0034 (2026-04-24) additionally supersedes the harness
implementation — `testcontainers.compose.DockerCompose` is replaced by
an in-tree subprocess builder under `tests/integration/harness/`. The
per-service topology described below (per-service images, one compose
file, per-test Compose project, `docker compose run` for `things-cli`,
`docker run` for the AppleScript contract) is unchanged.

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

## Amendment — 2026-04-23

The *"One Compose project per service, separate Dockerfiles"*
alternative above was rejected on the basis that all four CLIs ship
from the same `pyproject.toml`, so a shared image buys no isolation. That
premise no longer holds: issue [#105](https://github.com/aidanns/agent-auth/issues/105)
splits the repo into per-service subprojects, each with its own
`pyproject.toml`, `install.sh`, and release tag namespace. Keeping a
single `Dockerfile.test` across services would re-couple those
deliverables at the test-image layer once #105 lands.

Issue [#95](https://github.com/aidanns/agent-auth/issues/95) reverses the
"one image" sub-decision as the enabling prep step for #105. The rest
of ADR 0005 stands (per-test Compose project, in-container
`things-cli` tests with a file-backed credential store, bridge config
shipped inline via `configs:`, `scripts/verify-integration-isolation.sh`
gating the topology).

Concretely, the following sub-decisions change:

- **Per-service Dockerfiles replace `docker/Dockerfile.test`.** Each
  of `Dockerfile.agent-auth.test`, `Dockerfile.things-bridge.test`,
  `Dockerfile.things-cli.test`, and
  `Dockerfile.things-client-applescript.test` is fully self-contained
  (no shared `Dockerfile.base.test`). `pip install .` installs the
  whole project today; #105 swaps it to
  `pip install ./packages/<service>/` per Dockerfile.
- **Compose services point at per-service images.** The
  `docker-compose.yaml` template now carries one placeholder per image
  (`AGENT_AUTH_TEST_IMAGE`, `THINGS_BRIDGE_TEST_IMAGE`,
  `THINGS_CLI_TEST_IMAGE`) and drops the `agent-auth` / `things-bridge`
  `entrypoint` overrides (each image has its own default
  `ENTRYPOINT`). The notifier sidecar continues to reuse the
  agent-auth image with an explicit entrypoint override because it
  runs `python -m tests_support.notifier`, a different process than
  `agent-auth serve`.
- **`things-cli` runs in its own short-lived container.** The test
  harness calls `docker compose run --rm things-cli` against the new
  `things-cli` Compose service instead of `docker compose exec`'ing
  into the bridge. The 0600 credentials file is now owned by the
  container's UID inside a per-test bind-mounted tmpdir on the host;
  no shared-UID compromise is required.
- **Per-session image tags.** The harness builds `<service>-test:<session>`
  for each service at session start. CI exposes the session id via
  `AGENT_AUTH_TEST_IMAGE_SESSION` (replacing the previous single
  `AGENT_AUTH_TEST_IMAGE_TAG`); `scripts/verify-integration-isolation.sh`
  enforces that every per-service Dockerfile exists and that the old
  `Dockerfile.test` is absent.

The `tests/things_client_fake/` module now lives in both the
`things-bridge` image (invoked as the bridge's `things_client_command`
subprocess) and the `things-client-applescript` image (the fake is the
stand-in that image's contract tests exercise on Linux). The
duplication is ~10 lines of Dockerfile and mirrors the production
split: after #105, the fake will travel with the AppleScript CLI's
test assets and the bridge will either pin a fixed test-helper package
or continue to carry its own copy.
