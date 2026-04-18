# ADR 0002 — Docker-based HTTP integration tests

## Status

Accepted — 2026-04-18.

## Context

`tests/test_server.py` drove HTTP behaviour by starting
`ThreadingHTTPServer` on `127.0.0.1:0` in a daemon thread and reaching
into the in-process `TokenStore`, `AuditLogger`, and a mocked keyring.
That shape has two problems:

1. **Host-level collisions under parallel runs.** Even with a
   kernel-assigned port, each run holds a `tempfile.TemporaryDirectory`
   on the host's filesystem, a patched keyring, and a SQLite file.
   Concurrent runs on the same host (parallel CI workers; a local dev
   run concurrent with another branch) race on those shared surfaces.
   Called out on
   [PR #4#discussion_r3086381389](https://github.com/aidanns/agent-auth/pull/4#discussion_r3086381389)
   and tracked as [#7](https://github.com/aidanns/agent-auth/issues/7).
2. **Violates the public-API-only testing standard.** Tests imported
   `store.get_family`, `store.mark_family_revoked`, and signed tokens in
   the test process using the same signing key the server held. They
   were unit tests dressed as integration tests and could not catch a
   regression in the CLI → config → server wiring.

## Considered alternatives

### Pytest free-port plugin

A fixture that claims an unused TCP port on `127.0.0.1` and exports it.

**Rejected** because:

- Doesn't isolate the SQLite database, the keyring, the audit log, or
  `~/.config/agent-auth/`. Those collisions — not the port — are the
  actual failure mode.
- Requires keeping the in-process tests, which bypass the CLI and the
  config loader, so the "integration" tests still don't exercise the
  surface a real deployment goes through.

### Keep the in-process tests, isolate state with `monkeypatch`

Patch `XDG_CONFIG_HOME` / `XDG_DATA_HOME` per-test so the SQLite and
config paths land in a tmpdir, and keep using kernel-assigned ports.

**Rejected** because it does not address the public-API testing
concern, and because the real compose / CLI / config path still is not
exercised.

### Docker container per test (chosen)

Build a test image from the working-tree source, run one Compose
project per test (named by a uuid), map `127.0.0.1::9100` for an
ephemeral host port, and drive the container exclusively through its
HTTP API and `agent-auth` CLI.

## Decision

Adopt the Docker-per-test approach.

- `docker/Dockerfile.test` installs `agent-auth[tests-support]` plus
  `keyrings.alt` so the server can start without an interactive keyring
  backend.
- `docker/compose.test.yaml` defines a single `agent-auth` service that
  binds `127.0.0.1::9100` (ephemeral).
- `tests/integration/conftest.py` exposes
  `agent_auth_container` (default) and `agent_auth_container_factory`
  (for custom TTLs / approval env) fixtures. Each test gets its own
  Compose project name, so containers do not share state or ports.
- Tests call the HTTP API directly and use
  `container.exec_cli(...)` to invoke `agent-auth` inside the container
  when they need to create / revoke tokens or inspect family state.
- A new `tests_support.env_plugin` notification plugin (env-var
  driven, defaults to deny) gives the integration layer control over
  prompt-tier approvals without a stdin.
- `scripts/verify-integration-isolation.sh` enforces that
  `tests/integration/` never references `127.0.0.1` / `0.0.0.0`
  directly and that the pytest fixture still builds
  `docker/Dockerfile.test`.

## Consequences

- Integration tests need Docker + Compose on the host (including inside
  the shared devcontainer — see the README **Development** section for
  the rootless-DinD preference and rationale).
- Integration tests are slower: image build on first run + per-test
  container startup. Mitigated by running the unit layer first in CI
  and only gating on integration after unit passes.
- The `tests_support` package is shipped alongside `agent-auth` and
  loaded by `importlib.import_module` inside the running server, which
  means it falls under the same plugin-trust caveat
  ([#6](https://github.com/aidanns/agent-auth/issues/6)). Acceptable
  here because the package is installed *only* when the image is built,
  not in production.
- `/agent-auth/health` is added as a readiness probe (satisfying the
  `service-design.md` health-endpoint standard).

## Follow-ups

- Pin `docker/Dockerfile.test`'s base image by digest once the CI
  runner has a stable tag/digest mapping.
- Revisit container scope if integration-test wall-clock time becomes a
  problem — module- or session-scope containers are a straightforward
  knob on the factory fixture.
