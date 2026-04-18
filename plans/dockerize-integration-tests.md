# Implementation Plan: Dockerize HTTP integration tests

Addresses [#7](https://github.com/aidanns/agent-auth/issues/7).

## Context

The HTTP tests in `tests/test_server.py` run an in-process
`ThreadingHTTPServer` bound to `127.0.0.1` on a kernel-assigned ephemeral
port, and drive it in-process (threaded server + direct `TokenStore` /
`AuditLogger` handles). Two problems fall out of that shape:

1. Even with `port=0`, the tests share the host's network, SQLite files in
   `tempfile.TemporaryDirectory`, and the patched keyring state. Concurrent
   runs on the same host (parallel CI jobs, a local dev run while another
   branch is running) collide on those shared surfaces and are a standing
   PR-review concern
   ([PR #4#discussion_r3086381389](https://github.com/aidanns/agent-auth/pull/4#discussion_r3086381389)).
2. The tests reach into internal state (`store.get_family`,
   `store.mark_family_revoked`) rather than exercising the public HTTP +
   CLI surface, so they are strictly *unit tests dressed as integration
   tests*. `testing-standards.md` requires integration-test isolation and
   public-API-only assertions.

This PR converts the HTTP tests into a true black-box integration layer
that drives a containerised `agent-auth serve` through its HTTP API and
CLI, with each test run getting its own network namespace and filesystem.

## Scope

In scope:

- Add a `GET /agent-auth/health` endpoint (required for the container
  readiness probe and already mandated by `service-design.md`).
- Add a `tests_support.env_plugin` notification plugin (packaged in an
  optional extras group) that returns approve / deny based on an env var,
  so prompt-tier flows are exercisable end-to-end without stdin.
- Add `docker/Dockerfile.test` and `docker/compose.test.yaml` that build
  `agent-auth` at the working-tree commit and run `agent-auth serve` in a
  container with the file-backed keyring and the env plugin.
- Introduce a `tests/integration/` layer gated by a `pytest` marker
  (`integration`), with a fixture that starts a container, waits on
  `/agent-auth/health`, yields the mapped base URL, and tears down.
- Move the existing HTTP tests from `tests/test_server.py` into
  `tests/integration/`, rewriting them to use the container fixture and
  the CLI/HTTP public surface. Unit-level tests that need direct store
  manipulation stay in `tests/test_server.py` as in-process tests of the
  handler module.
- Update `scripts/test.sh` to support `--integration` / `--all` modes and
  the GH Actions workflow to run both layers.
- Add `scripts/verify-integration-isolation.sh` that asserts the
  regression checks from the issue.
- Add an ADR recording the container-based isolation decision.
- Document the rootless-DinD preference for running the integration tests
  inside a devcontainer, in the README's **Development** section.

Out of scope:

- A generic pytest free-port plugin (alternative rejected in the ADR).
- Rate-limiting / DoS posture for the health endpoint (tracked
  separately via `service-design.md` rate-limit TODO).
- Replacing the `terminal` production plugin.
- Moving the plugin out-of-process (tracked in #6).

## Dependencies

- No new runtime deps on `agent-auth` itself.
- Dev extras gain `keyrings.alt` for the file-backed keyring used inside
  the test container.
- Test host needs Docker (rootless DinD when inside the devcontainer,
  whatever the runner provides in CI). Documented in README.

## File Structure

```
docker/
    Dockerfile.test                # Test image: installs agent-auth from /src
    compose.test.yaml              # Compose file building the test image
    entrypoint.test.sh             # Seeds config + starts `agent-auth serve`
src/agent_auth/
    server.py                      # Add health handler
tests_support/                     # New package, installed via [tests-support] extra
    __init__.py
    env_plugin.py                  # Env-var-driven NotificationPlugin
tests/
    test_server.py                 # Only the unit-level subset stays here
    integration/
        __init__.py
        conftest.py                # Docker fixture (session + function scopes)
        test_health.py            # Health endpoint
        test_validate.py           # Validate: allow / invalid / scope-denied / prompt
        test_refresh.py            # Refresh: success + reuse detection
        test_status.py             # Status endpoint
        test_reissue.py            # Reissue with short refresh TTL
scripts/
    test.sh                        # Adds --unit / --integration / --all
    verify-integration-isolation.sh  # Regression check from issue
.github/workflows/
    test.yml                       # Runs unit then integration
    verify-standards.yml           # Runs verify-integration-isolation.sh
design/decisions/
    0001-docker-integration-tests.md
README.md                          # "Development" section with docker + DinD notes
```

## Implementation Phases

### Phase 1 — Health endpoint

1. Add `_handle_health` in `server.py` that opens a read-only query
   (`SELECT 1`) via `store` and returns `200 {"status": "ok"}` on success,
   `503 {"status": "unhealthy"}` on store error. Route `GET /agent-auth/health`.
2. Unit test in `tests/test_server.py`.
3. Update `design/DESIGN.md` to list the endpoint, and
   `design/functional_decomposition.yaml` to add a leaf function
   *Serve Health Endpoint* allocated to a unit and an integration test.

### Phase 2 — Env-driven notification plugin

1. Create `tests_support/env_plugin.py` with
   `EnvPlugin(NotificationPlugin)` whose `request_approval` returns an
   `ApprovalResult` built from `AGENT_AUTH_TEST_APPROVAL` (values:
   `approve`, `deny`). Defaults to `deny` so a misconfigured container
   fails closed.
2. Register `tests_support` as an installable package in `pyproject.toml`
   under `[project.optional-dependencies] tests-support`.
3. Unit test in `tests/test_env_plugin.py`.

### Phase 3 — Docker image

1. `docker/Dockerfile.test` (`python:3.12-slim` base) copies the repo,
   runs `pip install -e ".[dev,tests-support]" keyrings.alt`, exposes
   `9100`, and hands off to `entrypoint.test.sh`.
2. `docker/entrypoint.test.sh` writes a `config.json` seeded from env
   (host, port, TTLs, `notification_plugin=tests_support.env_plugin`) and
   execs `agent-auth serve`.
3. `docker/compose.test.yaml` defines a `test` profile service that
   builds the Dockerfile, maps `127.0.0.1::9100` (ephemeral), passes
   `AGENT_AUTH_TEST_APPROVAL` and TTL overrides as env, and names the
   container deterministically per-run via `${AGENT_AUTH_TEST_RUN_ID}`.
4. File-backed keyring initialised on container start via
   `PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring` — ephemeral
   per container, never shared.

### Phase 4 — Pytest fixture

1. `tests/integration/conftest.py` exposes:
   - `agent_auth_container` (function scope by default): generates a
     unique run id (`uuid4().hex`), runs `docker compose -f docker/compose.test.yaml -p <run-id> up -d --build`, polls
     `GET /agent-auth/health` up to 30s, yields a dataclass
     `{base_url, run_id, exec}` where `exec` is a helper that runs a CLI
     command inside the container via `docker compose exec`.
   - Teardown runs `docker compose -p <run-id> down -v`.
2. Register the `integration` marker in `pyproject.toml` so
   `pytest -m "not integration"` works for the unit layer.

### Phase 5 — Rewrite tests as black-box

For each test moved into `tests/integration/`:

- Tokens are created by invoking `agent-auth token create --json` inside
  the container and parsing stdout.
- Family state is inspected via `agent-auth token list --json` (no direct
  store access).
- Reissue tests use a container started with very short
  `refresh_token_ttl_seconds` (e.g. 1s) plus `time.sleep` to let the
  refresh token expire, rather than back-dating rows in the DB.
- Prompt-tier tests set `AGENT_AUTH_TEST_APPROVAL=approve|deny` on the
  container env.

Unit-level coverage that still needs in-process manipulation (e.g.
handler branches for malformed JSON, unknown routes) remains in
`tests/test_server.py` using the existing `_start_server` helper — but
that helper is renamed `_start_in_process_server` and clearly documented
as unit-scope only.

### Phase 6 — CLI / CI wiring

1. `scripts/test.sh` grows `--unit` (default), `--integration`, `--all`.
   Integration mode requires Docker and builds the image once per run.
2. `.github/workflows/test.yml` splits into two jobs: `unit` (runs
   `scripts/test.sh --unit`) and `integration` (runs `scripts/test.sh --integration` on a runner with Docker).
3. `scripts/verify-integration-isolation.sh` asserts:
   - No file under `tests/integration/` contains a raw `127.0.0.1`
     host-bind literal (allowed only in assertions against the fixture's
     `base_url`).
   - The CI workflow contains a step that builds `docker/Dockerfile.test`.
   - The `integration` marker is registered in `pyproject.toml`.
4. Wire the new verification script into a new
   `.github/workflows/verify-standards.yml` workflow.

### Phase 7 — Docs, ADR, design updates

1. `design/decisions/0001-docker-integration-tests.md` — context, decision
   (container-per-test), rejected alternative (free-port plugin — doesn't
   isolate SQLite/keyring), and consequences (Docker required for
   integration tests, slower local feedback, clean isolation).
2. `design/DESIGN.md` — add health endpoint to API table; add a short
   "Testing" section describing the unit / integration split.
3. `design/functional_decomposition.yaml` and
   `design/product_breakdown.yaml` — allocate the new *Serve Health
   Endpoint* function to product components and to a unit + integration
   test each.
4. `README.md` — add a **Development** section covering:
   - `scripts/test.sh --unit` vs `--integration` vs `--all`.
   - Docker requirement for integration tests.
   - Rootless DinD preference when running inside the shared
     devcontainer, with the rationale from the issue comment (scope-bypass
     avoidance, sibling-vs-nested semantics, reproducibility, no
     `--privileged`), and known tradeoffs.

## Design and verification

- **Verify implementation against design doc** — after implementation,
  diff the actual endpoints, CLI commands, plugin names, and XDG paths
  against `design/DESIGN.md` and reconcile. Health is being added, so
  `DESIGN.md` gets the entry and the decomposition is updated.
- **Threat model** — no net change to the production threat surface: the
  `tests_support` plugin is shipped only via an extras group and the test
  container image; production users install `agent-auth` without it. The
  file-backed plaintext keyring is only used inside the ephemeral test
  container, which holds no real user data. The health endpoint returns
  no sensitive information and uses no authentication — consistent with
  the existing `/agent-auth/metrics` precedent called out in
  service-design.md. Append a short note in `SECURITY.md` (create if
  missing) recording these decisions.
- **Architecture Decision Records** — ADR-0001 captures the Docker
  decision and the rejected free-port alternative.
- **Cybersecurity standard compliance** — no new user-exposed surface in
  production; the changes are test-only + the already-planned health
  endpoint. Walk through the selected standard's relevant controls and
  confirm no gap.
- **Verify QM / SIL compliance** — the project's declared QM/SIL level
  requires traceable test coverage for each leaf function; the new
  *Serve Health Endpoint* function is allocated to a unit and an
  integration test.

## Post-implementation standards review

- **coding-standards.md** — run through naming and type conventions on
  the new code (fixture dataclass, env plugin, helpers). Add `NewType`
  wrappers for the run-id and base-URL if they cross trust or semantic
  boundaries. Name TTL overrides with explicit seconds suffixes.
- **service-design.md** — confirm health meets the health-check
  standard, that the compose file does not persist defaults to disk,
  that the container listens on `0.0.0.0` inside and maps to an
  ephemeral loopback port outside, and that graceful shutdown (SIGTERM)
  still works.
- **release-and-hygiene.md** — pin the `docker/Dockerfile.test` base
  image by digest (not just tag) so CI is reproducible. Confirm the
  `tests-support` extra is documented.
- **testing-standards.md** — confirm the new integration tests exercise
  only HTTP + CLI (no `store` / `audit` imports in `tests/integration/`),
  and that `scripts/verify-integration-isolation.sh` guards against
  future drift. Add a brief function-to-test allocation note for health.
- **tooling-and-ci.md** — confirm `scripts/test.sh --all` is the
  single-command test runner and that every check script
  (`verify-function-tests.sh`, `verify-design.sh`, the new
  `verify-integration-isolation.sh`) is wired into CI.
- **python.md / bash.md** — lint the new Python and bash files using the
  project's configured tools.

## Verification

1. `scripts/test.sh --unit` passes on a host without Docker.
2. `scripts/test.sh --integration` builds the image, starts containers,
   waits on health, runs every test in `tests/integration/`, and tears
   down cleanly. No leftover containers or volumes on exit.
3. Running two copies of `scripts/test.sh --integration` concurrently on
   the same host completes without collisions.
4. `scripts/verify-integration-isolation.sh` passes; forcing a raw
   `127.0.0.1` literal into a file under `tests/integration/` makes it
   fail.
5. `curl http://<mapped>/agent-auth/health` returns `200 {"status": "ok"}` against a running container.
6. Every CI job is green on the PR.
