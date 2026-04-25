<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan — Docker-backed integration tests for gpg-bridge (issue #278)

## Goal

Add a Docker-backed integration test slice for the gpg signing
workflow (`gpg-cli` → `gpg-bridge` → `gpg-backend-cli-host` → real
`gpg`). Mirror the existing per-service split (agent-auth +
things-bridge + things-cli) so the workflow joins
`task test -- --integration <svc>` and a per-service CI job.

Core acceptance:

- `task test -- --integration gpg-bridge` runs the full workflow
  locally against Docker.
- An `integration-gpg-bridge` CI job runs on every PR and gates
  `all-integration-tests`.
- At least one test asserts the real authz path (token created via
  agent-auth → sign succeeds; revoked token → sign fails 401/403).
- At least one test asserts real `gpg --verify` succeeds (`GOODSIG` /
  `VALIDSIG` status lines), not just subprocess return code.
- `gpg` absence in CI image is a test failure, not a silent skip.

## Topology

Two new test images parallel the things-bridge split:

- `docker/Dockerfile.gpg-bridge.test` — devcontainer-side image
  carrying the `gpg-bridge` HTTP server. Default ENTRYPOINT
  `gpg-bridge serve`.

- `docker/Dockerfile.gpg-backend.test` — "host"-side image carrying
  `gpg-backend-cli-host` plus the real `gpg` binary, plus a throwaway
  `GNUPGHOME` baked at image build with one test signing key. No
  ENTRYPOINT (invoked as a subprocess of the bridge via
  `gpg_backend_command` over the docker network using
  `docker compose exec gpg-backend gpg-backend-cli-host …`). Note:
  `gpg-bridge` shells out to its backend via subprocess, so we cannot
  cross containers via subprocess directly. Instead the bridge's
  `gpg_backend_command` is set to a shim script that does the
  cross-container exec, OR we install `gpg-backend-cli-host` and `gpg`
  into the same container as the bridge.

  **Decision:** install `gpg-backend-cli-host` + `gpg` + the seeded
  `GNUPGHOME` into the *same* container as `gpg-bridge` (one image:
  `Dockerfile.gpg-bridge.test`). The "host" / "devcontainer" split is
  a deployment artefact of the production topology — at the
  integration test layer we still exercise the real subprocess
  contract (bridge spawns `gpg-backend-cli-host` which spawns `gpg`),
  just inside one container so the subprocess hop is honest. A
  separate `docker/Dockerfile.gpg-cli.test` image hosts `gpg-cli` for
  the devcontainer side (no `gpg`, no key material).

  This keeps the Compose topology simple (`agent-auth` + `gpg-bridge`
  long-running services + `gpg-cli` `on-demand`-profile service for
  per-test CLI invocations) and matches how `things-bridge` works:
  the bridge container also runs the backend subprocess.

  Issue body's two-Dockerfile suggestion (`Dockerfile.gpg-bridge.test`

  - `Dockerfile.gpg-backend.test`) was an artifact of imagining the
    host/container split end-to-end; honouring the production deployment
    shape doesn't require splitting the integration image. Document this
    in the PR body.

## Test key strategy

The image must have a real GPG keypair available so `gpg-bridge`'s
`sign` and `verify` paths exercise actual cryptography.

Options considered:

1. **Bake the key at image build time** — generate the key inside the
   Dockerfile via `gpg --batch --gen-key` so every container starts
   with the same fingerprint, no per-test setup. Faster, fewer moving
   parts, deterministic.
2. **Generate the key per-test in a tmpdir + bind-mount as
   GNUPGHOME** — adds key generation to every test fixture. Slower,
   more flake surface (GPG key generation on a CI runner can take
   seconds with low entropy).

**Decision:** option 1. The key is throwaway by construction (random
unattended passphrase-free key generated at image build, never
exported), the test image is `<svc>-test:<session>` and never
published, and a stable fingerprint baked into the image lets the
test fixture surface it via `docker exec gpg-bridge gpg --list-secret-keys --with-colons` once at session start. PR body will
record this decision.

The integration tests assert the bridge's `allowed_signing_keys`
config is honoured by setting it to the baked fingerprint and
asserting a different fingerprint returns 403.

## Compose topology

`docker/docker-compose.yaml` gains:

```yaml
gpg-bridge:
  image: ${GPG_BRIDGE_TEST_IMAGE}
  ports:
    - "127.0.0.1::9300"
  configs:
    - source: gpg_bridge_config
      target: /home/agent-auth/.config/gpg-bridge/config.yaml
      mode: 0644
  depends_on:
    - agent-auth
  stop_grace_period: 5s

gpg-cli:
  image: ${GPG_CLI_TEST_IMAGE}
  profiles:
    - on-demand
  stop_grace_period: 5s
```

…plus a `gpg_bridge_config` block defining `allowed_signing_keys`,
`auth_url: http://agent-auth:9100`, and `gpg_backend_command`
(default `["gpg-backend-cli-host"]` since we're in the same
container).

The agent-auth + gpg-bridge fixture wraps both into a `GpgBridgeStack`
similar to `ThingsBridgeStack`.

## Test fixtures

New `packages/gpg-bridge/tests/integration/conftest.py` defines:

- `GpgBridgeStack` dataclass — wraps cluster, agent-auth handle, and a
  GPG-aware client.
- `gpg_bridge_stack_factory` fixture — same shape as
  `things_bridge_stack_factory`. Spins up the agent-auth +
  gpg-bridge pair and surfaces the test signing key fingerprint.
- `gpg_cli_invoker` fixture — runs `gpg-cli` in a per-test
  short-lived container via `docker compose run --rm gpg-cli`,
  bind-mounting any required config / payload tmpdir, with env vars
  for bridge URL and bearer token (matching `AGENT_AUTH_GPG_*` env
  surface).

The bridge stack code lives in
`packages/agent-auth-common/src/tests_support/integration/plugin.py`
(same module as the existing things-bridge / agent-auth fixtures) so
all per-package conftests share the cluster and image-build wiring.

## Test cases

In `packages/gpg-bridge/tests/integration/test_gpg_bridge.py`:

1. **Real authz path — sign succeeds with valid token.** Mint a
   `gpg:sign=allow` token via the in-container agent-auth CLI, drive
   `gpg-cli` in its own container to detached-sign a payload, assert
   exit 0 and that the resulting signature begins with
   `-----BEGIN PGP SIGNATURE-----`. Then verify the signature against
   the same bridge and assert `GOODSIG` / `VALIDSIG` appears in the
   status output.
2. **Revoked token returns 401.** Same as 1 but revoke the token via
   `agent-auth token revoke <family>` between mint and use; assert
   `gpg-cli` exits non-zero with `unauthorized` (or 401 surfaced via
   the client error type).
3. **Wrong scope returns 403.** Mint a token without `gpg:sign`,
   assert 403 / `scope_denied`.
4. **Expired access token returns 401 token_expired.** Use the
   factory's `access_token_ttl_seconds=1` knob.
5. **Backend / authz unavailable.** Stop `agent-auth` mid-test; bridge
   surfaces 502 `authz_unavailable`.
6. **Allowlist enforcement.** Bridge config carries
   `allowed_signing_keys: [<fp>]`; signing with a different
   fingerprint returns 403 `key_not_allowed` without invoking the
   backend. (Cheap path that exercises bridge-config wiring under the
   real authz layer.)
7. **Real `gpg --verify` succeeds end-to-end.** Verify-only test —
   sign once via the bridge, then call `gpg-cli --verify` against the
   same payload + signature and assert the verify path returns 0 and
   emits `[GNUPG:] VALIDSIG` / `[GNUPG:] GOODSIG`.
8. **Health endpoint requires `gpg-bridge:health` scope.** Mirrors the
   things-bridge contract test.

(7) overlaps with (1) — keep both for clarity, or fold (7) into (1).
Final naming: keep (1) the "sign + verify happy path" and drop (7)
as a separate test.

## Existing smoke test (Option A vs B)

The issue defers this. The test at
`packages/gpg-bridge/tests/test_gpg_end_to_end.py`:

- Already exercises gpg-cli → gpg-bridge → backend → real gpg.
- Skips silently when `gpg` is missing.
- Uses `_NoopAuthz` (does not exercise real authz).

**Decision: Option B — delete the smoke test.** Once the Docker
suite lands, the smoke test is strictly weaker (no authz, less
coverage, silent-skip is an acceptance violation). Keeping a
duplicate adds maintenance cost without coverage. Removing it also
satisfies the "no silent skip" acceptance criterion without needing
to convert the skip into a failure (which would block local dev runs
on macOS where `gpg` may not be installed).

## Plumbing changes

- `packages/agent-auth-common/src/tests_support/integration/support.py`
  — add `gpg-bridge` and `gpg-cli` entries to
  `PER_SERVICE_DOCKERFILES`.
- `packages/agent-auth-common/src/tests_support/integration/plugin.py`
  — extend `_compose_image_env` to include the new image vars,
  `_resolve_test_image_tags` to cover them. Add `GpgBridgeStack`,
  `gpg_bridge_stack_factory`, `gpg_bridge_stack`, `GpgCliInvoker`
  helpers.
- `docker/docker-compose.yaml` — add `gpg-bridge` and `gpg-cli`
  services + `gpg_bridge_config` block.
- `docker/Dockerfile.gpg-bridge.test` — bridge + backend + gpg + key.
- `docker/Dockerfile.gpg-cli.test` — gpg-cli only (no key material).
- `packages/gpg-bridge/tests/integration/__init__.py` (no-op /
  collection root).
- `packages/gpg-bridge/tests/integration/conftest.py` — collection
  marker + per-package fixtures specific to the bridge.
- `packages/gpg-bridge/tests/integration/test_gpg_bridge.py` —
  test bodies.
- `scripts/test.sh` — `SERVICE_PATHS["gpg-bridge"]` plus
  `UNIT_IGNORE_OPTS` entry for `packages/gpg-bridge/tests/integration`.
- `.github/workflows/test.yml` — `integration-gpg-bridge` job
  (mirrors `integration-things-bridge`); add to `tests.needs`.
- `.github/actions/build-integration-test-image/action.yml` — extend
  the for-loop to build the new images.
- `scripts/verify-integration-isolation.sh` — add the gpg
  integration tree to the dirs list and the new Dockerfiles to the
  required-Dockerfile list.
- Delete `packages/gpg-bridge/tests/test_gpg_end_to_end.py`.
- `pyproject.toml` workspace — adjust the mypy `module` overrides
  list (drop `test_gpg_end_to_end`).
- `packages/gpg-bridge/pyproject.toml` — review `--cov-fail-under` if
  removing the smoke test reduces measured coverage; ratchet down
  only as needed (per-package gate).

## ADR

Add `design/decisions/0036-or-next-gpg-bridge-docker-tests.md` (a new
ADR matching ADR 0005's pattern for the gpg surface). Reuse the ADR
0005 / 0033 prose where applicable; key delta is the throwaway-key
strategy and the single-image rationale.

## Out of scope

- Cross-host signing / TLS posture. Bridge config in the test image
  uses plaintext loopback (mirrors the existing things-bridge test
  config). Production posture (TLS via `tls_cert_path` /
  `tls_key_path`) is exercised by the unit tests and is not part of
  this issue.
- Rate-limit fault injection (would require driving a custom rate
  limit config on agent-auth — the bridge's posture inherits from
  agent-auth's rate limiter, which is already covered by the
  agent-auth integration suite).

## Standards review (per `plan-template.md`)

- **Verify implementation against design doc.** ADR 0033 (gpg-bridge)
  and ADR 0005 (per-service Docker tests). New ADR for the gpg-bridge
  Docker test slice.
- **Threat model.** Threat model in `SECURITY.md` covers gpg signing.
  No security-relevant change here — the test layer doesn't change
  the production trust boundary. Note: the test image carries a
  throwaway key. Document that the key never leaves the image, the
  image isn't published, and the keyring carries no passphrase
  protection because the test runner needs unattended access. A
  dedicated section in the ADR records this.
- **Coding standards.** Naming, types, and safety rules — apply to
  new conftest / test code.
- **Service design standards.** No change to bridge config schema,
  health endpoint, etc.
- **Release-and-hygiene.** Test assets only; no version bump path
  triggered.
- **Testing standards.** Tests exercise the public HTTP surface; the
  signing path is asserted via real `gpg --verify` per the
  acceptance criterion.
- **Tooling-and-CI.** New `integration-gpg-bridge` job feeds the
  aggregate `tests` job; updated composite action builds the new
  images.

## Implementation sequence

1. Plan committed (this file).
2. Add the two Dockerfiles and the `docker-compose.yaml` gpg
   service + config block.
3. Extend `tests_support/integration` plugin and support to know
   about gpg images.
4. Write the integration tests + conftest under
   `packages/gpg-bridge/tests/integration/`.
5. Wire into `scripts/test.sh`, `verify-integration-isolation.sh`,
   `.github/workflows/test.yml`, and the composite action.
6. Delete the old smoke test; update mypy override list.
7. Add ADR.
8. Local verification: at minimum `task lint`, `task check`,
   `task verify-standards`. Skip the live Docker run if Docker is
   unavailable in this environment — CI gates the live path.
9. Self-review (`git diff main...HEAD`) before push.
