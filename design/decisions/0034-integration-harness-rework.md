<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0034 — In-tree `DockerComposeCluster` harness for integration tests

## Status

Accepted — 2026-04-23. Supersedes the `testcontainers-python`
implementation choices from ADR 0004 § Decision ("using
`testcontainers-python` to drive the Compose lifecycle instead of
hand-rolled subprocess calls") and ADR 0005 § Decision (single shared
Compose file). The broader decisions from 0004 / 0005 — per-test
Compose project, shared `Dockerfile.test`, one `docker-compose.yaml`
for all services — are unchanged. Closes
[#80](https://github.com/aidanns/agent-auth/issues/80).

## Context

ADR 0004 adopted `testcontainers-python` to drive the per-test Compose
lifecycle, and ADR 0005 extended the same pattern to the `things-*`
services. The conftest layers in `tests/integration/` grew three
friction points that were called out on #80:

1. **Placeholder-rendered compose file.** The shared
   `docker/docker-compose.yaml` carried `{{ COMPOSE_PROJECT_NAME }}`
   / `{{ AGENT_AUTH_TEST_IMAGE }}` / `{{ THINGS_BRIDGE_TEST_FIXTURES_DIR }}`
   double-brace placeholders that the conftest substituted via a
   Python renderer (`render_compose_file`) before docker compose ever
   saw the file. The rendered file was self-contained, but the
   substitution mechanism was bespoke — reading the compose file alone
   didn't reveal what the tests actually ran.
2. **Handwritten readiness polling.** `wait_until_server_ready` was
   an HTTP loop in `tests/integration/_support.py` that every
   per-service conftest imported and called after `compose.start()`.
   Service readiness was expressed imperatively rather than declared on
   a cluster definition.
3. **Untyped port discovery.** Host and port came from
   `compose.get_service_host(svc, 9100)` /
   `compose.get_service_port(svc, 9100)` — two positional lookups
   string-concatenated into `base_url`. Negative tests that needed
   to shell out directly (`stop_agent_auth`, the `things-cli`
   invoker) also hand-rolled their own `docker compose` argv.

There was no `docker compose logs` capture on teardown either — a
flaky integration test left no artefact for post-mortem, so CI
reproduction meant re-running locally.

`palantir/docker-compose-rule` (JUnit rule for Compose-backed tests)
addresses the same concerns with a fluent builder, typed port
accessors, declarative wait strategies, and log capture on failure.
That shape ported cleanly.

## Considered alternatives

### Keep `testcontainers-python` and bolt on the missing pieces

Wrap `DockerCompose` with our own readiness + log-capture helpers
and keep the Python-side template renderer.

**Rejected** because:

- `DockerCompose` in testcontainers 4.x does not expose
  `project_name=`; the conftest's workaround writes
  `COMPOSE_PROJECT_NAME` into `os.environ` before every
  `start()` / `stop()`. The Python-side renderer sidestepped that
  by baking the project into the rendered compose file, but it layers
  yet another templating mechanism on top of the one docker compose
  already provides natively.
- `exec_in_container` wraps `subprocess.run(check=True)` and
  raises on non-zero exit, so the `things-cli` invoker already
  bypasses it and shells out to `docker compose exec` by hand. Two
  subprocess paths for the same API surface is worse than one.
- Every feature we would add (wait strategies, log capture, typed
  ports) has a near-identical JUnit precedent to borrow from; the
  wrapper would be thicker than the thing it wraps.

### Port testcontainers upstream

Contribute `project_name=` and log capture back to
`testcontainers-python`.

**Rejected.** Valuable generally, but the review / release cycle of an
upstream library is the wrong thing to block our integration-test
ergonomics on, and the ADR 0004 harness already duplicates a single
caller's worth of logic on top of testcontainers (subprocess for
`docker build`, bespoke readiness polling). A small in-tree harness
is cheaper in aggregate.

## Decision

Replace `testcontainers-python` in the integration-test harness with
an in-tree `DockerComposeCluster` module under
`tests/integration/harness/`. Headline properties:

- **Fluent builder.** `DockerComposeCluster.builder().project_name(x) .file(...).env(K, V).waiting_for_service(name, HealthChecks.…) .save_logs_to(dir, on_success=False).build()` — configuration is
  explicit and local to the fixture.
- **Subprocess-native.** Every action (`config`, `up`, `port`,
  `exec`, `stop`, `logs`, `down`) is a direct `docker compose`
  CLI invocation, so every harness failure maps 1:1 to a command a
  developer can reproduce. The test runner never calls into a
  third-party Python library for container lifecycle.
- **Project name on the CLI.** `--project-name` is passed on the
  command line; configured env vars flow into the subprocess via
  `subprocess.run(env=...)`. `os.environ` is never mutated.
- **Typed port accessor.** `running.service("agent-auth").port(9100)`
  returns a `DockerPort` dataclass (`host` / `external_port` /
  `internal_port`) with `in_format("http://$HOST:$EXTERNAL_PORT")`
  — no more hand-rolled string concatenation.
- **Declarative wait strategies.** `HealthChecks.to_respond_over_http`
  and `HealthChecks.to_have_ports_open` cover the common cases; custom
  callables `(ServiceHandle) -> (bool, diagnostic)` cover the rest.
  Per-service waits run in parallel under a shared deadline: the first
  unhealthy service fails the whole startup instead of waiting the full
  timeout on every sibling.
- **Log capture on teardown.** `save_logs_to(dir, on_success=False)`
  dumps `docker compose logs <service>` into `dir/<service>.log`
  before `docker compose down` runs, so a flaky CI run leaves an
  artefact to upload.
- **Compose file uses native interpolation.** The shared
  `docker/docker-compose.yaml` now uses `${AGENT_AUTH_TEST_IMAGE}`
  / `${AGENT_AUTH_TEST_CONFIG_DIR}` / `${THINGS_BRIDGE_TEST_FIXTURES_DIR}`
  / `${NOTIFIER_MODE}`. `render_compose_file` and the
  `COMPOSE_PROJECT_NAME` placeholder are gone; the project name is
  passed via `--project-name`. One substitution mechanism, not two.
- **Pre-flight validation.** `docker compose config --quiet` runs
  before `up` so a typo in the compose file surfaces as "bad file"
  rather than "container exited immediately".
- **No external dependency.** `testcontainers[compose]` is dropped
  from the `dev` extra and from the `tool.mypy.overrides` shim.

`tests/integration/conftest.py` and
`tests/integration/things_bridge/conftest.py` are rewritten on this
harness; the `things-cli` invoker funnels `docker compose exec`
through `StartedCluster.exec` so compose wiring lives in one place.
`tests/integration/_support.py` keeps the session-scoped image-build
helper, the docker-availability probe, the empty-fixture seed, and the
structured phase-timing logger; `wait_until_server_ready` and
`render_compose_file` are deleted.

## Consequences

- The integration suite no longer installs `testcontainers-python` —
  the `dev` extra shrinks by one transitive graph. Docker + docker
  compose remain required on the host (same as before).
- Every fixture-layer action maps to a CLI invocation a developer can
  reproduce on the command line, which shortens the loop when a test
  fails only on CI.
- `docker compose port` output is parsed from the right (`host, _, port_str = first_line.rpartition(":")`) so IPv6-bracketed hosts
  still round-trip correctly. The parse is unit-tested.
- Wait strategies are arbitrary callables; a careless probe that
  performs heavy work on every poll can slow the whole suite. The
  built-in `HealthChecks` stay cheap (a single HTTP GET or TCP
  connect); custom probes are the caller's responsibility.
- `save_logs_to(on_success=False)` needs the pytest node's per-phase
  report to branch on test outcome. The top-level conftest installs a
  `pytest_runtest_makereport` hook that exposes the reports on the
  item, and a shared `_test_failed(request)` helper reads them — a
  tiny fixture-layer dependency that every per-service teardown now
  shares.
- ADR 0004's Follow-ups entry "pin the base image by digest" is
  unchanged. The "container scope" follow-up remains — the harness's
  fluent builder makes a session-scoped `DockerComposeCluster`
  straightforward to introduce if wall-clock becomes the bottleneck,
  but that's a future lever rather than today's move.

## Follow-ups

- Consider exposing harness unit tests as a smoke gate in CI once the
  integration runner stabilises on the new pattern.
- If a second consumer outside this repo grows interest in the same
  harness, lift it under `tests/` into a reusable internal package.
  For now, a single caller doesn't justify the extra API surface.
