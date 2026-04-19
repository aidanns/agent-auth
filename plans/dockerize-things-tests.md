# Implementation Plan: Dockerize things-bridge / things-cli / things-client e2e tests

Addresses [#78](https://github.com/aidanns/agent-auth/issues/78). Extends
the per-test Docker pattern that PR
[#67](https://github.com/aidanns/agent-auth/pull/67) introduced for
`agent-auth` (see ADR `design/decisions/0004-docker-integration-tests.md`)
to the remaining services in the repo.

## Context

The `agent-auth` HTTP integration tests now run black-box in
`tests/integration/`, driven by `testcontainers.compose.DockerCompose`
through a per-test Compose project. Each test gets an isolated container,
filesystem, and ephemeral host port.

The other services in this repo still rely on in-process tests that thread
a `ThreadingHTTPServer` on `127.0.0.1:0`, share host SQLite/keyring state,
and reach into private classes (`FakeAuthz`, `_InjectableThings`,
`_BridgeHandler`). They suffer the same host-port / shared-state collision
risk that motivated the `agent-auth` migration and skip the compose / CLI
/ config wiring entirely:

- **`things-bridge`** — `tests/test_things_bridge_e2e.py` runs both
  `agent-auth` and `things-bridge` as in-process threaded servers and
  shells out to the fake Things client subprocess. Two services + a
  background subprocess on every test, all sharing host state.
  `tests/test_things_bridge_server.py` is a more focused HTTP-routing
  test that uses the bridge in-process with `FakeAuthz` / fake Things
  store. `tests/test_things_bridge_authz.py` is a pure unit test of the
  authz client.
- **`things-cli`** — `tests/test_things_cli_client.py` drives the
  refresh / reissue flow through two in-process fake HTTP servers (one
  for the bridge, one for `agent-auth`). It never sees the real bridge
  or the real `agent-auth`, so contract drift between any two of those
  three components is invisible.
- **`things-client-cli-applescript`** — the AppleScript binary itself is
  macOS-only and cannot run in a Linux container. The
  JSON-on-stdout/exit-code contract that the bridge depends on is shared
  with the `tests.things_client_fake` CLI under
  `things_client_common.cli`, so the protocol is exercisable in Linux
  via the fake. The bridge-side e2e migration above already exercises
  the contract through the real subprocess invocation path; what is
  missing is a Dockerised contract test that pins the wire protocol
  itself (envelope shapes, exit codes, error mapping) so a refactor of
  the shared CLI scaffold can't silently change behaviour the
  AppleScript CLI also relies on.

## Scope

In scope:

- Add `GET /things-bridge/health` endpoint (mirrors the
  `service-design.md` requirement and the agent-auth pattern). It is
  unauthenticated — the bridge holds no secrets and the endpoint is the
  Compose readiness probe; tests treat any HTTP response as "up".
- Reuse the existing `docker/Dockerfile.test` (it already installs every
  console-script entry point in `pyproject.toml`, including
  `things-bridge` and `things-cli`). Extend it to also place
  `tests/things_client_fake/` on `PYTHONPATH` so
  `python -m tests.things_client_fake` resolves inside the container.
- Add `docker/compose.test.things-bridge.yaml` — a multi-service Compose
  project that runs `agent-auth` + `things-bridge` together and bind-mounts
  per-test config dirs into both services.
- Add `docker/config.test.things-bridge.yaml` — baseline `things-bridge`
  config used by the per-test fixture (auth URL pointing at the
  in-network `agent-auth` service, fake Things client command, sane
  TTLs).
- Add `tests/integration/things_bridge/conftest.py` with fixtures that
  build a per-test Compose project, mint a token via the in-container
  `agent-auth` CLI, write a Things fixture YAML into the bridge's
  bind-mounted volume, and yield a `ThingsBridgeContainer` handle.
- Add `tests/integration/things_cli/conftest.py` reusing the
  `things-bridge` Compose stack and adding `things-cli` invocation
  helpers. Tests run `things-cli` inside the container so credential
  storage, HTTP wiring, refresh/reissue retries, and the contract with
  the bridge are all exercised black-box.
- Add `tests/integration/things_client_applescript/conftest.py` and
  `test_contract.py` that run the fake CLI inside the test image to
  validate the JSON-on-stdout protocol. The AppleScript CLI itself
  remains macOS-only and is exercised by the existing Darwin-only suite.
- Move (or retire) in-process tests:
  - `tests/test_things_bridge_e2e.py` → moved to
    `tests/integration/things_bridge/`, rewritten as black-box HTTP
    tests against the Compose stack.
  - `tests/test_things_bridge_server.py` — kept as unit-level HTTP
    routing tests of the in-process bridge (deletes private class
    references that duplicate the integration suite; trims down to
    routing/error-mapping coverage that the integration tests don't
    duplicate).
  - `tests/test_things_bridge_authz.py` — kept as a unit test of the
    authz HTTP client.
  - `tests/test_things_cli_client.py` — split: the refresh/reissue retry
    decision logic stays as a unit test against the in-process fake
    handlers (one assertion per retry path), but the happy-path HTTP
    flow moves to integration.
  - `tests/test_things_client_cli_contract.py` — moved to
    `tests/integration/things_client_applescript/test_contract.py`,
    rewritten to run the fake CLI inside the container.
- Extend `scripts/verify-integration-isolation.sh` to scan every
  service's integration subdirectory (not just the top-level
  `tests/integration/`) for raw loopback references and require each
  service's `conftest.py` to reference its `Dockerfile.test` and a
  `compose.test.*.yaml` file.
- Add a new ADR (`design/decisions/0005-things-services-docker-tests.md`)
  describing the per-service migration, the multi-service Compose
  topology for `things-bridge`, and the decision to skip a true e2e of
  the AppleScript CLI in Linux.

Out of scope:

- A real Things 3 / `osascript` integration test on macOS — that lives
  in the existing `_requires_things3`-gated suite and a follow-up macOS
  GitHub-hosted runner workflow.
- Switching the JIT approval plugin protocol to out-of-process — the
  existing `tests_support.always_approve` / `always_deny` plugins are
  reused; #6 covers the broader plugin-trust migration.
- Adding metrics endpoints to the Things services. They belong in a
  dedicated follow-up so the migration here doesn't snowball.

## Approach

### Image strategy

`docker/Dockerfile.test` already runs `pip install .`, which installs
every entry point in `pyproject.toml` — `agent-auth`, `things-bridge`,
`things-cli`, and `things-client-cli-applescript`. The same image can be
the per-service runtime; Compose overrides `entrypoint`/`command` per
service. The Dockerfile gains:

- A copy of `tests/things_client_fake/` placed under
  `/opt/tests-support/tests/things_client_fake/` so
  `python -m tests.things_client_fake --fixtures …` works inside the
  container without an installed distribution.
- A copy of `tests/__init__.py` (empty marker) into
  `/opt/tests-support/tests/__init__.py` so `tests` resolves as a
  package.

The `tests_support` exclusion in `[tool.setuptools.packages.find]`
already keeps both packages out of the production wheel; the same
guarantee covers the fake client because it lives under `tests/`.

### things-bridge stack

`docker/compose.test.things-bridge.yaml` declares two services:

- `agent-auth` — same image, runs `agent-auth serve`, bind-mounts a
  per-test config dir to `/home/agent-auth/.config/agent-auth/`.
- `things-bridge` — same image, runs `things-bridge serve`,
  bind-mounts a per-test config dir to
  `/home/agent-auth/.config/things-bridge/` and a Things fixture file
  (read-only) to a known path. Connects to `agent-auth` via the Compose
  network using `auth_url: http://agent-auth:9100`.

The bridge port is exposed as `127.0.0.1::9200`; the agent-auth port is
*not* exposed externally (tests reach it via the in-container CLI).

### Per-test fixture

`tests/integration/things_bridge/conftest.py` exposes a
`things_bridge_stack` fixture that:

1. Mints a per-test Compose project name (UUID).
2. Writes the agent-auth config (existing `config.test.json` + per-test
   overrides) and the bridge config (`config.test.things-bridge.yaml`
   pointing at the seeded fixture path) into separate per-test tmp
   dirs.
3. Writes the Things fixture YAML the fake client should serve.
4. Starts the Compose project, waits for both services to be reachable
   (agent-auth: existing `/health` poll; bridge: new `/things-bridge/health`).
5. Mints a token via `agent-auth-container.exec_cli("token", "create",
   "--scope", "things:read", ...)` and yields the bridge base URL,
   bearer token, and helpers for revoking / re-fetching family state.

### things-cli fixture

`tests/integration/things_cli/conftest.py` reuses the same
`things_bridge_stack` Compose topology, adds a third *ephemeral* service
(or an exec-only invocation pattern, depending on what reads
ergonomically — leaning toward `compose.exec` so credentials live in a
named volume that the test can inspect). Provides helpers to:

- Run `things-cli login --bridge-url … --auth-url … --access-token …
  --refresh-token … --family-id …` inside the container, persisting
  credentials to a per-test path.
- Run `things-cli todos list --json` and parse the output.

### things-client-cli-applescript contract test

`tests/integration/things_client_applescript/test_contract.py` runs the
fake CLI inside the test image via `compose.exec_in_container([
"python", "-m", "tests.things_client_fake", "--fixtures", "…", …])`
and re-asserts every shape the bridge depends on. This subsumes
`tests/test_things_client_cli_contract.py` for the Linux container
path; the AppleScript-specific tests in
`tests/test_things_client_applescript_things.py` stay where they are.

### Verification script

`scripts/verify-integration-isolation.sh` currently hard-codes
`tests/integration/` and a single `conftest.py`. It is updated to:

- Iterate every immediate subdirectory of `tests/integration/` (the new
  per-service layout) plus the existing top-level files.
- For each subdirectory, require that the local `conftest.py` (or one
  inherited from `tests/integration/conftest.py`) references
  `docker/Dockerfile.test` and a `compose.test.*.yaml` file.
- Reject `127.0.0.1` / `0.0.0.0` literals in any subdirectory's test
  files (excluding `conftest.py`), preserving the existing rule.

## Risks and mitigations

- **CI wall-clock time** — adding three more docker-build + per-test
  start cycles inflates the integration job. The image is already built
  once per session; the new tests reuse the cached layer. Per-test
  start is ~1–2s with Compose v2 on Linux. Mitigation: keep the unit
  layer fast and gate integration to run only after unit passes.
- **Multi-service Compose teardown race** — Compose can leave dangling
  networks if `compose stop` is interrupted. The existing
  `agent_auth_container_factory` already wraps stop in a try/except;
  the new factory mirrors that pattern.
- **Credential file mode collision in CLI tests** — `things-cli` writes
  credentials to a 0600 file. The bind-mounted volume must allow the
  container UID to write; we use a tmpfs or anonymous volume scoped to
  the Compose project rather than a host bind so file modes match.
- **Contract drift between the AppleScript CLI and the fake** — the
  Linux contract test only validates the fake's behaviour. The shared
  `things_client_common.cli` already routes both through the same
  argparse + envelope code; the existing macOS-gated test
  `test_things_client_applescript_things.py::test_helper_applescript_is_valid_syntax`
  catches AppleScript-specific drift. Documented in the new ADR.

## Design and verification

- **Verify implementation against design doc** — after implementation,
  diff `design/DESIGN.md` and `design/THINGS.md` against the new test
  topology; reconcile or update.
- **Threat model** — no new trust boundaries are introduced (the
  Compose network is internal to the test runner). `SECURITY.md`
  unchanged.
- **Architecture Decision Records** — new ADR `0005` covers the
  per-service migration, multi-service Compose topology, and the
  decision to skip Linux-side e2e of the AppleScript CLI.
- **Cybersecurity standard compliance** — no production behaviour
  changes; the `/things-bridge/health` endpoint is added under the same
  rationale as `/agent-auth/health`.
- **QM / SIL compliance** — verification artefacts in
  `design/ASSURANCE.md` reference the integration test layer; updated
  to include the new per-service suites.

## Post-implementation standards review

- **`coding-standards.md`** — fixture / helper functions named with
  verbs; per-service packages and modules use lowercase snake_case;
  numeric constants carry units in their names.
- **`service-design.md`** — health endpoint required for HTTP services
  (added); per-test bind-mounted YAML is the single source of truth for
  config; XDG paths preserved inside the container.
- **`release-and-hygiene.md`** — no version-bump; required project
  files unchanged.
- **`testing-standards.md`** — integration tests exercise public HTTP +
  CLI surfaces only; `covers_function` markers on new tests track
  function-to-test allocation.
- **`tooling-and-ci.md`** — `scripts/test.sh --integration` already
  picks up everything under `tests/integration/`; no new entry points
  required. Verification script wired into `task check`.
