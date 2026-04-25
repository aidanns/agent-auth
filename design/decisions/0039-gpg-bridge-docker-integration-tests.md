<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0039 — Per-service Docker integration tests for the gpg-bridge surface

## Status

Accepted — 2026-04-25.

Extends [ADR 0005](0005-things-services-docker-tests.md) (the per-test
Compose pattern shared by the things-\* services) to the gpg signing
surface defined in [ADR 0033](0033-gpg-bridge-cli-split.md). The
harness implementation rework in [ADR 0034](0034-integration-harness-rework.md)
applies unchanged: this ADR adds gpg-bridge to the per-service set the
existing in-tree harness already drives.

## Context

The gpg signing workflow (`gpg-cli` → `gpg-bridge` →
`gpg-backend-cli-host` → real `gpg`) was covered by in-process unit
tests plus a single end-to-end smoke test
(`packages/gpg-bridge/tests/test_gpg_end_to_end.py::TestEndToEnd::test_gpg_cli_sign_and_verify_via_bridge`).
The smoke test:

- stubbed authz with `_NoopAuthz` so the real
  agent-auth-token-validation path was never gated;
- silently skipped (`pytest.mark.skipif`) when the host had no `gpg`
  binary, so an image regression that dropped `gpg` would land green;
- ran in-process, never exercising the cross-process / cross-network
  trust boundaries the production deployment crosses.

Every other service in the workspace
(`agent-auth`, `things-bridge`, `things-cli`,
`things-client-applescript`) has a Docker-backed integration suite
under `packages/<svc>/tests/integration/` and a dedicated
`integration-<svc>` job in `.github/workflows/test.yml`. The gpg
surface needs to join that tier so the bridge's authz integration,
its allowlist, and the real-`gpg` verify path are all gated on every
PR. Tracked in [#278](https://github.com/aidanns/agent-auth/issues/278).

## Considered alternatives

### Two compose services — `gpg-bridge` (devcontainer-side) and `gpg-backend` (host-side) — split across two images

Mirror the production deployment shape exactly: one container running
`gpg-bridge` HTTP, a sibling container running `gpg-backend-cli-host`
plus the real `gpg` binary plus the throwaway `GNUPGHOME`. The bridge
would shell out to a wrapper script that `docker exec`s the backend
container.

**Rejected** because:

- `gpg-bridge` invokes its backend via `subprocess.Popen` —
  cross-container subprocess communication needs an in-bridge wrapper
  binary that adds a moving part the production deployment does not
  have. A wrapper bug at the test layer would either mask a real
  contract regression or invent a failure mode the production code
  never sees.
- The honesty argument is "the bridge spawns a real subprocess, that
  subprocess spawns the real `gpg`" — both of those happen inside one
  container exactly as cleanly as across two. The container boundary
  is a deployment artefact, not a contract the bridge enforces.
- Two-image splits double the image-build cost in CI for no test
  signal. The existing `things-bridge` integration runs the bridge and
  its `things_client_command` subprocess inside one container; the gpg
  pattern stays consistent.

### Skip-fail conversion — keep the in-process smoke test, make `gpg`-absence a hard failure

Convert the smoke test's `skipif` into a `fail`-shaped marker so an
image / runner regression that drops `gpg` is loud.

**Rejected** because:

- Doesn't address the `_NoopAuthz` gap — the real authz path stays
  untested.
- Local-dev runs on macOS without `gpg` on the host would hard-fail
  the unit suite. The existing integration tier is the right home for
  binaries-on-PATH dependencies; unit tests should remain runnable on
  any developer machine without external prereqs.

### Per-test key generation in a tmpdir + bind-mount as `GNUPGHOME`

Generate a fresh signing keypair inside each test's compose stack
(`gpg --batch --gen-key` against a per-test `GNUPGHOME` tmpdir
bind-mounted into the bridge container).

**Rejected** because:

- ed25519 key generation under low-entropy CI runners can take
  seconds. Per-test cost would exceed the existing per-test compose
  start budget by ~5×.
- The key is throwaway by construction. A baked, image-local key
  achieves the same security property — never published, never
  exfiltrated — at zero per-test cost.

## Decision

Add a per-package `packages/gpg-bridge/tests/integration/` slice
following the ADR 0005 / ADR 0034 pattern, and:

- **Two new test images.** `docker/Dockerfile.gpg-bridge.test`
  carries the bridge plus `gpg-backend-cli-host` plus the host `gpg`
  binary plus a throwaway `GNUPGHOME` baked at image build with two
  ed25519 signing keys. `docker/Dockerfile.gpg-cli.test` carries
  `gpg-cli` only — no `gpg`, no key material — mirroring the
  devcontainer-side / host-side split at the image boundary even
  though the integration topology runs both halves in one compose
  network. The two-key pattern lets the allowlist test assert the
  deny path against a real second fingerprint instead of a synthetic
  string.
- **Profile-gated services in the shared compose file.** The new
  `gpg-bridge` and `gpg-cli` services live in
  `docker/docker-compose.yaml` under `profiles: [gpg]`; the gpg
  fixture passes `COMPOSE_PROFILES=gpg` so existing agent-auth and
  things-bridge fixtures continue to start exactly the subset they
  did before. No harness change is needed — `COMPOSE_PROFILES` is the
  documented compose-side knob for this.
- **Throwaway-key strategy: bake at image build.** The `RUN gpg --batch --gen-key` step in the gpg-bridge Dockerfile generates two
  passphrase-free ed25519 keys into a per-image `GNUPGHOME`. Every
  build of the test image produces different fingerprints, so tests
  must discover the fingerprint at session start
  (`gpg --list-secret-keys --with-colons` inside the container) — no
  hardcoding. The image is `gpg-bridge-test:<session>` and never
  published; `Dockerfile.gpg-cli.test` deliberately carries no key
  material.
- **Stack fixture and CLI invoker.** `GpgBridgeStack` + the
  `gpg_bridge_stack` / `gpg_bridge_stack_factory` fixtures live in
  `tests_support.integration.plugin` alongside the existing
  `ThingsBridgeStack` fixtures (one shared place for cross-service
  compose plumbing). The `GpgCliInvoker` helper is per-package because
  no other suite consumes it; it wraps `docker compose run --rm gpg-cli` and exposes typed `sign(...)` / `verify(...)` calls so each
  test reads as HTTP-shaped operations rather than subprocess argv.
- **Coverage of the four issue-#278 acceptance points.** The new
  suite asserts: (a) sign-then-real-`gpg`-verify happy path, (b) real
  authz failure on a revoked token, (c) wrong-scope 403, (d)
  expired-token 401 `token_expired`, (e) `authz_unavailable` when
  agent-auth is down mid-test, (f) unknown-fingerprint failure mode,
  (g) `/gpg-bridge/health` requires a token. The verify assertion
  pins `[GNUPG:] GOODSIG` / `[GNUPG:] VALIDSIG` rather than just exit
  code 0.
- **Delete the in-process smoke test.** Once the Docker suite lands,
  `packages/gpg-bridge/tests/test_gpg_end_to_end.py` is strictly
  weaker (no authz, silent-skip on `gpg` absence, in-process). The
  removal also satisfies the issue's "no silent skip" acceptance
  criterion without forcing a hard-fail on dev machines without
  `gpg`. Coverage of the bridge's HTTP handler stays measured by
  `test_gpg_bridge_server.py` (which uses the same in-process server
  pattern with `gpg_backend_fake`).
- **CI wiring.** `integration-gpg-bridge` job in
  `.github/workflows/test.yml`, listed in the `tests` aggregate's
  `needs:`. The `build-integration-test-image` composite action
  builds both new images alongside the existing four under the shared
  `AGENT_AUTH_TEST_IMAGE_SESSION` tag.

## Consequences

### Positive

- Real `gpg` signature production and verification gated on every
  PR. An image regression that drops the `gnupg` apt package or the
  baked key fails the integration job loudly; an authz regression
  that lets a revoked token sign fails the same job.
- The `_NoopAuthz` gap is closed. Bridge authz is exercised against a
  live agent-auth service in every signing test.
- Pattern stays consistent: `packages/<svc>/tests/integration/`,
  `--integration <svc>`, `integration-<svc>` job, all the same.

### Negative / accepted trade-offs

- Two more images in the integration build set, ~30 s of additional
  CI cache-cold image-build time per per-PR run (cache-warm
  amortises). The cost is local to the gpg-bridge job — other
  per-service jobs aren't slowed.
- The throwaway-key bake step adds ~1 s to a cold gpg-bridge image
  build. Acceptable given GHA cache reuse on warm builds.
- The test image carries an unprotected, passphrase-free secret key.
  The image is never published (`<svc>-test:<session>` tags only,
  cleaned up at session end), is never used by production, and
  carries no real-world identity. Documented in the Dockerfile
  comment so a future reader doesn't misread the absence of
  `%passphrase` as an oversight.

### STRIDE / threat-model deltas

No production trust boundary changes. The integration test layer
honours the production split (bridge runs the backend subprocess via
its existing `gpg_backend_command` config; the bridge talks to
agent-auth over HTTP for token validation), it just collapses host
and devcontainer onto one Docker network. The new test artefacts
(throwaway key, baked `GNUPGHOME`) live exclusively inside ephemeral
test images.

## Follow-ups

- **Backend timeout fault-injection.** Issue #278's failure-mode list
  mentions backend timeout. Achievable today by stacking a custom
  config layer that sets `request_timeout_seconds` low and a
  configurable backend that sleeps; the closest analogue
  (`things-bridge` request timeout) is also covered at the unit tier.
  Tracked as a follow-up if the gpg-specific path ever regresses.
- **TLS posture in integration tests.** The bridge's plaintext
  loopback path is what the test image uses. The TLS posture is
  covered by unit tests today; pinning it end-to-end in the Docker
  suite would need certificate generation per session and is deferred
  until #217's required-signatures re-enablement makes it material.
