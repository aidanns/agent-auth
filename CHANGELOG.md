<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0](https://github.com/aidanns/agent-auth/compare/agent-auth-v0.1.0...agent-auth-v0.2.0) (2026-04-22)


### ⚠ BREAKING CHANGES

* ` → major, `feat:` → minor,

### Features

* add client-level FakeThingsClient for Linux e2e testing ([#53](https://github.com/aidanns/agent-auth/issues/53)) ([7013a0f](https://github.com/aidanns/agent-auth/commit/7013a0f786ff61fe43e500d0f766194d105bfde7))
* add release artifacts — CHANGELOG, LICENSE, SECURITY, install.sh, release automation ([#96](https://github.com/aidanns/agent-auth/issues/96)) ([4bb02a3](https://github.com/aidanns/agent-auth/commit/4bb02a3a476b33a59f925f353f81f9e698e475f3))
* add Taskfile.yml (go-task) as unified task runner ([#59](https://github.com/aidanns/agent-auth/issues/59)) ([d082a70](https://github.com/aidanns/agent-auth/commit/d082a70bd36ffd795b729862efd309dfacca92d2))
* **api:** publish OpenAPI 3.1 specs for agent-auth and things-bridge ([#176](https://github.com/aidanns/agent-auth/issues/176)) ([b782b04](https://github.com/aidanns/agent-auth/commit/b782b047e377243a4bdb32ee3d95f8bdc664edbb))
* **audit:** add schema_version field and stability policy ([#167](https://github.com/aidanns/agent-auth/issues/167)) ([eecc9d6](https://github.com/aidanns/agent-auth/commit/eecc9d62760f81f4b7cafc2b55fb0cd2567e2e54))
* **audit:** attach OTel service.name/service.version to every audit entry ([#100](https://github.com/aidanns/agent-auth/issues/100)) ([#200](https://github.com/aidanns/agent-auth/issues/200)) ([ad72be7](https://github.com/aidanns/agent-auth/commit/ad72be7f54c1a4108df0cf008e710604a7aa763d))
* **ci:** adopt mdformat, taplo, and keep-sorted tooling ([#75](https://github.com/aidanns/agent-auth/issues/75)) ([52258cc](https://github.com/aidanns/agent-auth/commit/52258cc309be12fa82f34fa4fbfb76edc0b041b3))
* expose token management operations via HTTP API ([#97](https://github.com/aidanns/agent-auth/issues/97)) ([20b73a9](https://github.com/aidanns/agent-auth/commit/20b73a97fbb8383e449f359b8d6948dd2c15bd5a))
* implement agent-auth server, CLI, and token management ([#4](https://github.com/aidanns/agent-auth/issues/4)) ([cded144](https://github.com/aidanns/agent-auth/commit/cded144537c4f3ce656982a50b0bbb9b6d4463a5))
* implement things-bridge and things-cli (read-only) ([#9](https://github.com/aidanns/agent-auth/issues/9)) ([3b40c8e](https://github.com/aidanns/agent-auth/commit/3b40c8eaf91bc9180cb66cacc69f4b5b78c31666))
* initial project scaffold with CLI entrypoint ([1070fbf](https://github.com/aidanns/agent-auth/commit/1070fbff32dd5c6527cbbec4bc050cb49c1935fd))
* **metrics:** /agent-auth/metrics and /things-bridge/metrics Prometheus endpoints ([#26](https://github.com/aidanns/agent-auth/issues/26)) ([#186](https://github.com/aidanns/agent-auth/issues/186)) ([6d266fb](https://github.com/aidanns/agent-auth/commit/6d266fbbddfd78c94ebb708d28e39f2c72bed969))
* migrate config to YAML, version APIs at /v1/, and add error/audit contract tests ([#126](https://github.com/aidanns/agent-auth/issues/126)) ([4c61c2a](https://github.com/aidanns/agent-auth/commit/4c61c2ae10f553ed115fd2bddbd3d2bfc483abe4))
* **release:** add --yes flag and document non-interactive signing ([#123](https://github.com/aidanns/agent-auth/issues/123)) ([e87da4a](https://github.com/aidanns/agent-auth/commit/e87da4ad8734af1fa7bfe5e3e495ae1dd9115887))
* **release:** attest SLSA Build L3 provenance on every release ([#109](https://github.com/aidanns/agent-auth/issues/109)) ([#180](https://github.com/aidanns/agent-auth/issues/180)) ([7eb1efd](https://github.com/aidanns/agent-auth/commit/7eb1efd3c35f86dcb8e6e69259ac08d3c710040c))
* **release:** signed SBOMs, autorelease via Release Please, REUSE compliance ([#132](https://github.com/aidanns/agent-auth/issues/132)) ([38e257b](https://github.com/aidanns/agent-auth/commit/38e257b28bceba20c0110dddf01f020785f53974))
* **security:** adopt OWASP ASVS v5 as application security standard ([#177](https://github.com/aidanns/agent-auth/issues/177)) ([de46858](https://github.com/aidanns/agent-auth/commit/de4685815f4bdca146c0f3049476c537a4374c62))
* **server:** graceful SIGTERM / SIGINT shutdown for agent-auth and things-bridge ([#154](https://github.com/aidanns/agent-auth/issues/154)) ([#162](https://github.com/aidanns/agent-auth/issues/162)) ([600a901](https://github.com/aidanns/agent-auth/commit/600a9014a4a5989115cc24f157e137a524a73857))
* **things-bridge:** deepen /health to verify things-client binary is resolvable ([#91](https://github.com/aidanns/agent-auth/issues/91)) ([#198](https://github.com/aidanns/agent-auth/issues/198)) ([4f93930](https://github.com/aidanns/agent-auth/commit/4f93930a833d916ca89156f9cdbee64c25356552))
* **tls:** optional in-process TLS listener on both HTTP servers ([#101](https://github.com/aidanns/agent-auth/issues/101)) ([#201](https://github.com/aidanns/agent-auth/issues/201)) ([076fa6d](https://github.com/aidanns/agent-auth/commit/076fa6dd35f8bb3ed61881323aca36cff2c52fd3))
* **typecheck:** ratchet agent_auth/* to strict mypy + pyright ([#164](https://github.com/aidanns/agent-auth/issues/164)) ([35a95e4](https://github.com/aidanns/agent-auth/commit/35a95e488a13177e11147471aaca39725fc4c25d))
* **typecheck:** ratchet tests/ + tests_support/ under strict mypy + pyright ([#171](https://github.com/aidanns/agent-auth/issues/171)) ([f51a9f6](https://github.com/aidanns/agent-auth/commit/f51a9f6843aa73b831f1c8f4e56be46f84a364d2))
* **typecheck:** ratchet things_bridge/* to strict mypy + pyright ([#156](https://github.com/aidanns/agent-auth/issues/156)) ([5f090a7](https://github.com/aidanns/agent-auth/commit/5f090a77fc3913e1cac489d76cbc0a4e5717b648))
* **typecheck:** ratchet things_cli/* + things_client_common/* + things_models/* to strict ([#161](https://github.com/aidanns/agent-auth/issues/161)) ([b0f76f9](https://github.com/aidanns/agent-auth/commit/b0f76f9a86c8e3955625ca342fc426168022d17b))
* **verify-standards:** gate graceful-shutdown standard ([#32](https://github.com/aidanns/agent-auth/issues/32)) ([#188](https://github.com/aidanns/agent-auth/issues/188)) ([563c297](https://github.com/aidanns/agent-auth/commit/563c29770706aeaef57637d4352d6f78fbc89140))
* **verify-standards:** gate health-endpoint standard ([#25](https://github.com/aidanns/agent-auth/issues/25)) ([#179](https://github.com/aidanns/agent-auth/issues/179)) ([f01491f](https://github.com/aidanns/agent-auth/commit/f01491f943d6e1f68d1d278b177ec90497e20ed4))


### Bug Fixes

* move token management routes under /v1/ namespace ([#137](https://github.com/aidanns/agent-auth/issues/137)) ([#142](https://github.com/aidanns/agent-auth/issues/142)) ([0ead162](https://github.com/aidanns/agent-auth/commit/0ead162e6a037b767de8824256da23dd6411505e))
* **scripts:** rebuild venv when pyproject.toml changes; add service tasks ([#73](https://github.com/aidanns/agent-auth/issues/73)) ([60c38b3](https://github.com/aidanns/agent-auth/commit/60c38b32ec5c99c003d93ceea969f42bb9db711b))
* **server:** drain oversize request bodies before rejecting ([#144](https://github.com/aidanns/agent-auth/issues/144)) ([#199](https://github.com/aidanns/agent-auth/issues/199)) ([6c73ec1](https://github.com/aidanns/agent-auth/commit/6c73ec1e6b09c10c4ee37456155e4fab12777a94))
* **things-bridge:** log osascript timeouts to stderr ([#57](https://github.com/aidanns/agent-auth/issues/57)) ([63d2bcd](https://github.com/aidanns/agent-auth/commit/63d2bcdb9f839acb06ab0619b22a7350d8c618f5))
* **things-bridge:** repair AppleScript payload + log osascript failures ([#54](https://github.com/aidanns/agent-auth/issues/54)) ([29c3a39](https://github.com/aidanns/agent-auth/commit/29c3a39e77d31978881cb4d18596a7d063eb6408))


### Performance Improvements

* **things-bridge:** batch AppleScript property reads in list_todos ([#58](https://github.com/aidanns/agent-auth/issues/58)) ([53ea60d](https://github.com/aidanns/agent-auth/commit/53ea60d3869d70b3dde23fac453f6059e65c4800))

## [Unreleased]

### Added

- **Optional TLS listener on `agent-auth serve` and `things-bridge serve`.**
  Setting `tls_cert_path` + `tls_key_path` in `config.yaml` wraps the
  bound socket with `ssl.SSLContext(PROTOCOL_TLS_SERVER)` pinned to
  TLS 1.2+. Closes NIST SP 800-53 SC-8 for the
  devcontainer-to-host deployment, where plaintext bearer tokens
  previously crossed a virtual network interface between the
  devcontainer and the host. Plaintext remains the default — the
  loopback-only single-host bind already satisfies SC-8 without
  crypto. Half-configured TLS (only cert or only key set) raises
  `ValueError` at `Config.__post_init__` so the service cannot
  silently fall back to plaintext. `things-bridge`'s `AgentAuthClient`
  gains an `auth_ca_cert_path` config for trusting a self-signed
  agent-auth cert; `things-cli` gains a `--ca-cert` flag for the same
  job. New `tests/test_server_tls.py` and
  `tests/test_things_bridge_tls.py` drive a real TLS handshake via a
  `cryptography`-generated self-signed cert and assert the positive
  path, plaintext rejection, and untrusted-CA rejection.
  `SECURITY.md` SC-8 row flips from *Partial* to *Implemented*.
  README carries a devcontainer TLS recipe. Rationale in
  [ADR 0025](design/decisions/0025-tls-for-devcontainer-host-traffic.md).
  Closes [#101](https://github.com/aidanns/agent-auth/issues/101).

### Changed

- **Audit log entries now carry OTel resource attributes
  (`service.name`, `service.version`) on every line.** Consolidates
  the audit envelope across the system: SIEM consumers joining
  archived or multi-service trails can filter by emitter from the
  entry itself instead of inferring from the file path. The fields
  are constant today (`service.name = "agent-auth"`) because
  things-bridge is intentionally audit-free — every bridge
  authorization trace comes via agent-auth's `/validate` — but the
  envelope now matches what a second emitter would need, future-
  proofing multi-service consumers. Contract tests
  (`tests/test_audit_schema.py`) assert the resource attributes on
  every documented event kind so a rename fails CI. `schema_version`
  stays at `1` (new optional field per the stability policy).
  `design/DESIGN.md` §Audit log fields reframes the HTTP-attribute
  table as *reserved for future events*, aligning docs with what the
  code actually emits. Rationale in
  [ADR 0024](design/decisions/0024-audit-log-shared-envelope.md).
  Closes
  [#100](https://github.com/aidanns/agent-auth/issues/100).

- **`GET /things-bridge/health` now fails closed when the configured
  Things-client binary is missing.** The handler previously returned
  `200 {"status":"ok"}` unconditionally once the probe token
  authorised; it now also calls `shutil.which(things_client_command[0])`
  (cached for 30s to keep the probe cheap) and returns
  `503 {"status":"unhealthy"}` when resolution fails. agent-auth
  reachability stays covered implicitly by the probe-authorisation
  call, which already surfaces 502 `authz_unavailable` on upstream
  outage. `design/error-codes.md` documents the 503 body and
  `design/functional_decomposition.*` carry a new "Serve Bridge Health
  Endpoint" leaf function under Things Bridge. Rationale in
  [ADR 0023](design/decisions/0023-things-bridge-health-depth.md).
  Closes
  [#91](https://github.com/aidanns/agent-auth/issues/91).

- **`scripts/verify-standards.sh`'s mypy/pyright ratchet-drift gate
  now also covers per-diagnostic relaxations.** Previously the gate
  only paired mypy `ignore_errors = true` overrides with
  `pyrightconfig.json`'s top-level `ignore` list, so a narrower
  mypy override such as `disallow_untyped_defs = false` on
  `tests.*` (landed in #171) had no matching pyright-side check —
  a contributor could drop the pyright `executionEnvironments`
  root without the gate catching it. The check now also asserts
  every `[[tool.mypy.overrides]]` entry that sets any `disallow_*`
  flag to `false` has an `executionEnvironments` root in
  `pyrightconfig.json` relaxing the equivalent `reportMissing*` /
  `reportUnknown*` diagnostic, and vice versa.
  [`#175`](https://github.com/aidanns/agent-auth/issues/175).

### Added

- **macOS runner in the `Test` workflow** to exercise the real
  osascript path shipped in `things-client-cli-applescript`. The new
  `macos-applescript` job runs on `macos-14` (Apple Silicon) and
  drives `tests/test_things_client_applescript_things.py` against
  GitHub's pre-installed osascript so helper-AppleScript syntax
  errors, osascript stderr-wording changes, and subprocess-timeout
  handling get caught at merge time rather than on a contributor's
  laptop during review. A real Things 3 instance + Automation
  permissions aren't available on hosted macOS runners, so the
  `@_requires_things3` end-to-end tests auto-skip — extending
  coverage to a live Things database is tracked as follow-up. The
  job deliberately does not reuse
  `.github/actions/setup-toolchain` (Linux-asset URLs only) and
  instead bootstraps uv + the project venv directly. The
  aggregating `tests` job now fails on skip or failure of
  `macos-applescript` so a silently-skipped macOS job can't sneak
  through. Closes
  [#69](https://github.com/aidanns/agent-auth/issues/69).

### Changed

- **Release Please now authenticates via a dedicated GitHub App
  instead of a PAT.** `.github/workflows/release-please.yml` mints a
  short-lived installation token per workflow run via
  `actions/create-github-app-token` (pinned to `v3` commit SHA),
  using new repository secrets `RELEASE_PLEASE_APP_ID` +
  `RELEASE_PLEASE_APP_PRIVATE_KEY`. The "Release Please agent-auth"
  App scopes to `aidanns/agent-auth` only with `contents: write` +
  `pull-requests: write`, strictly narrower than a human-account
  PAT. The legacy `RELEASE_PLEASE_TOKEN` secret is retired; setup
  and rotation procedures are documented in `CONTRIBUTING.md` §
  *Release process → Default path*. ADR 0016 "Consequences" and
  "Follow-ups" updated. Closes
  [#128](https://github.com/aidanns/agent-auth/issues/128).

### Added

- **Performance budget** for the agent hot path
  (`POST /agent-auth/v1/validate`) documented in `design/DESIGN.md`
  § Performance budget along with budgets for
  `/v1/token/refresh` and `/v1/token/create`. A new perf-assertion
  test (`tests/test_perf_budget.py`) drives the validate endpoint
  against an in-process `AgentAuthServer` with N=100 sequential
  requests and fails CI if the measured median or p95 exceeds the
  budget. The test is discoverable as a group via
  `pytest -m perf_budget`; the marker is registered in
  `[tool.pytest.ini_options].markers`. `scripts/verify-standards.sh`
  asserts both pieces are present (the DESIGN.md heading, the
  marker registration, and at least one `@pytest.mark.perf_budget`
  test). Local baseline is p50=0.62ms / p95=1.00ms against budgets
  of 10ms / 50ms — the headroom absorbs CI-runner noise while
  still catching a regression that would add a per-request tax on
  every downstream bridge call. Closes
  [#41](https://github.com/aidanns/agent-auth/issues/41).
- Rate-limiting / DoS posture decision recorded in
  [ADR 0022](design/decisions/0022-rate-limiting-posture.md):
  1.0 defers application-layer rate limiting and relies on the
  loopback-only bind, the 1 MiB body cap, the 128-byte id-segment
  cap on the bridge, and `ApprovalManager`'s implicit per-family
  serialisation. `design/DESIGN.md` gains a new
  "Rate limiting and request budgets" section enumerating the
  expected steady / ceiling rate per endpoint.
  `scripts/verify-standards.sh` gates that some ADR carries
  "rate limit" / "DoS posture" / "denial of service" in its title
  so a future deletion fails CI
  ([#30](https://github.com/aidanns/agent-auth/issues/30)).
- Fault-injection test layer under `tests/fault/` exercising each
  documented failure mode: SQLite write errors / closed connection,
  audit-log disk-full / read-only filesystem, keyring backend
  unavailable, notification plugin timeout and generic exception,
  agent-auth unreachable from things-bridge, and Things subprocess
  client failures (missing binary, timeout, non-zero exit, non-JSON
  stdout). Each test asserts the typed error surfaces out of the
  component boundary and does not leak a raw third-party exception
  downstream. `scripts/verify-standards.sh` now asserts
  `tests/fault/` exists and contains coverage for each scenario;
  `design/SSDF.md` PW.8.2 ratcheted to *Implemented*. Closes
  [#39](https://github.com/aidanns/agent-auth/issues/39).
- `design/DESIGN.md` "Observability" now documents the full set of
  log streams (audit JSON-lines, operational stdout/stderr, the
  Prometheus scrape endpoint), the project's no-hierarchy log-level
  policy, log location and rotation expectations, and retention
  responsibilities — closing out the final gaps against
  `.claude/instructions/service-design.md`'s Observability-design
  standard. `scripts/verify-standards.sh` gates presence of each
  required topic so a future edit that drops one fails CI
  ([#33](https://github.com/aidanns/agent-auth/issues/33)).
- `scripts/verify-standards.sh` now gates the graceful-shutdown
  standard: both `src/agent_auth/server.py` and
  `src/things_bridge/server.py` must install a `signal.SIGTERM`
  handler, and at least one test under `tests/` must exercise
  SIGTERM shutdown behaviour. Comment-only references are stripped
  before the grep so a stale `# SIGTERM` cannot satisfy the gate
  after the real handler installation has been removed
  ([#32](https://github.com/aidanns/agent-auth/issues/32)).
- Mutation testing on the token-lifecycle and cryptographic/storage
  trust base (`tokens`, `crypto`, `keys`, `scopes`, `store` modules)
  via [mutmut](https://github.com/boxed/mutmut) v3.5 configured in
  `[tool.mutmut]`. A new nightly scheduled workflow
  (`.github/workflows/mutation.yml`) runs `task mutation-test`, which
  invokes mutmut over those five modules against the focused unit
  test files that exercise them and then gates the mutation score
  (`killed / (killed + survived)`) via
  `scripts/check-mutation-score.sh` against the floor in
  `[tool.mutation_score].fail_under` (initial floor 65.0; local
  baseline 68.95% — 262 killed / 380 actionable mutants).
  `CONTRIBUTING.md` § "Mutation score" documents the
  ratchet-upward-only policy; ADR 0021 records the rationale.
  `scripts/verify-standards.sh` gates presence of both the
  `[tool.mutmut]` / `[tool.mutation_score]` configuration and a
  scheduled workflow invoking the tool. `design/SSDF.md` PW.8.2
  updated from *Partial* → *Implemented for mutation testing*.
  Closes
  [#38](https://github.com/aidanns/agent-auth/issues/38).
- **`design/SELF_ASSESSMENT.md` — CNCF TAG-Security-style security
  self-assessment covering agent-auth, things-bridge, and things-cli
  as a system.** Structured around the
  [CNCF self-assessment template](https://tag-security.cncf.io/community/assessments/guide/self-assessment/)
  (Metadata, Overview, Self-Assessment Use, Security Functions and
  Features, Project Compliance, Secure Development Practices, Security
  Issue Resolution, Appendix). Cross-references the existing
  `SECURITY.md` threat model, `design/SSDF.md`, `design/ASVS.md`, and
  the ADR set; non-applicable items have explicit out-of-scope entries.
  `SECURITY.md` § Threat model links to the new doc as the system-level
  starting point. Closes
  [#114](https://github.com/aidanns/agent-auth/issues/114).
- Function-to-test coverage is now gated in CI. The last two uncovered
  leaf functions (`Auto Refresh Token`, `Load Notification Plugin`) now
  carry `@pytest.mark.covers_function(...)` annotations, bringing
  coverage to 57/57. The `verify-function-tests` workflow no longer
  carries `continue-on-error: true`, and `scripts/verify-standards.sh`
  asserts that the workflow keeps gating the check without that escape
  hatch
  ([#5](https://github.com/aidanns/agent-auth/issues/5)).
- **SLSA v1.0 Build Level 3 provenance on every release.**
  `release-publish.yml` now calls
  `slsa-framework/slsa-github-generator`'s
  `generator_generic_slsa3.yml` reusable workflow from a new
  `provenance` job (sequenced after `publish` via `needs:`), binding
  each sdist + wheel sha256 digest to the workflow run, commit SHA,
  and ref. The attestation ships as `multiple.intoto.jsonl` on every
  GitHub release. Verification recipe uses `slsa-verifier verify-artifact` with `--source-uri` + `--source-tag` pinning
  (documented in `SECURITY.md` § Supply-chain artifacts). Rationale
  and trust-boundary analysis in
  [ADR 0020](design/decisions/0020-slsa-build-provenance.md);
  `design/SSDF.md` PS.2.1 and PS.3.2 updated from *Planned* →
  *Implemented*. The `slsa-github-generator` reusable workflow must
  be tag-pinned (not SHA-pinned) because the generator introspects
  its own `@ref` to certify builder identity — policy exception
  documented in `.claude/instructions/tooling-and-ci.md`. Closes
  [#109](https://github.com/aidanns/agent-auth/issues/109).
- OWASP ASVS v5 adopted as the project's application-security
  verification standard at target Level 2. `design/ASVS.md` records
  per-chapter conformance (V1…V17) with evidence pointers and
  out-of-scope rationales; `SECURITY.md` gains an
  `## Application security standard` section linking the audit;
  ADR 0019 records the rationale and the relationship with the
  existing NIST SP 800-53 (cybersecurity), NIST SSDF (SDLC), and
  supply-chain companion standards.
  `scripts/verify-standards.sh` gates the new section. ADR 0015
  and `design/SSDF.md` now cross-reference `design/ASVS.md`
  directly instead of
  [#112](https://github.com/aidanns/agent-auth/issues/112)
  (closed by this change).
- `scripts/verify-standards.sh` now gates the health-endpoint standard:
  `/agent-auth/health` and `/things-bridge/health` must be registered in
  their server modules and tests must cover both a healthy (200)
  response and a subsystem-failure response (503 for agent-auth,
  502 for things-bridge). Deletes of the route or its unhealthy-case
  tests now fail CI
  ([#25](https://github.com/aidanns/agent-auth/issues/25)).
- `GET /agent-auth/metrics` and `GET /things-bridge/metrics`
  Prometheus scrape endpoints. Both emit text exposition
  format v0.0.4 gated by an `<service>:metrics` scope. Agent-auth
  tracks HTTP duration + active requests, validation outcomes by
  reason, token lifecycle operations, and JIT approval outcomes;
  things-bridge tracks HTTP duration + active requests. Names
  follow OTel semconv (ADR 0017); primitives live in the new
  `src/server_metrics/` package (Counter / Gauge / Histogram /
  Registry + text formatter). `design/DESIGN.md` "Observability"
  fills in the domain-counter catalogue previously deferred to
  this issue; `design/error-codes.md` gains `/metrics` taxonomy
  rows; OpenAPI specs add the endpoint on both services.
  `scripts/verify-standards.sh` gates the route registration and
  per-metric test coverage
  ([#26](https://github.com/aidanns/agent-auth/issues/26)).
- Published OpenAPI 3.1 specs for both HTTP surfaces:
  `openapi/agent-auth.v1.yaml` and `openapi/things-bridge.v1.yaml`.
  A contract test in `tests/test_openapi_spec.py` (1) validates both
  specs through `openapi-spec-validator`, (2) reflects on the
  server handlers and asserts every registered route has a matching
  spec path (catching both missing and stale entries), and (3)
  asserts every error code in the spec is documented in
  `design/error-codes.md`. `scripts/verify-standards.sh` gates
  existence of both spec files plus the contract test. README
  links the rendered specs
  ([#117](https://github.com/aidanns/agent-auth/issues/117)).
- Error taxonomy (`design/error-codes.md`) expanded to cover the
  agent-auth management endpoints (`token/create`, `token/modify`,
  `token/revoke`, `token/rotate`, `token/list`). Previously only the
  validation/refresh/reissue/health surfaces were enumerated.
- Audit-log `schema_version` field (currently `1`) emitted on every
  entry, with a documented stability policy in
  `design/DESIGN.md` "Audit log fields" and a contract test that
  fails if the version changes
  ([#20](https://github.com/aidanns/agent-auth/issues/20)).
- Community-health files to complete the GitHub Community Profile: Contributor
  Covenant v3.0 Code of Conduct, issue templates (bug report, feature request,
  security redirect), pull-request template, and SUPPORT.md. CoC and SUPPORT
  are referenced from `README.md` and `CONTRIBUTING.md`.
- Release Please autorelease workflow that maintains a release PR on every
  push to `main` and pushes a `vX.Y.Z` tag when the PR is merged.
- Tag-triggered publish workflow that builds the sdist and wheel, generates
  an SPDX 2.3 SBOM per artifact with Syft, signs every file (artifact and
  SBOM) with keyless Sigstore cosign, and uploads the bundle to the GitHub
  release. Verification recipe documented in `SECURITY.md`.
- REUSE 3.3 compliance: every tracked file carries an SPDX header (or is
  covered by `REUSE.toml`), a `reuse lint` CI workflow gates PRs, and the
  README renders the REUSE status badge.
- `ripsecrets` secret-scanning pre-commit hook and matching CI step to block
  accidental secret commits
  ([#42](https://github.com/aidanns/agent-auth/issues/42)).
- `treefmt --ci` CI gate to catch removal or misconfiguration of the
  formatter multiplexer
  ([#42](https://github.com/aidanns/agent-auth/issues/42)).
- `scripts/test.sh --fast` mode for a curated sub-second smoke subset of
  unit tests (tokens, scopes, crypto, keys); wired into `lefthook.yml`
  pre-commit ([#42](https://github.com/aidanns/agent-auth/issues/42)).
- NIST SSDF (SP 800-218 v1.1) adopted as the project's SDLC
  standard. `design/SSDF.md` records per-practice conformance for
  the PO / PS / PW / RV practice groups; `SECURITY.md` gains an
  `## SDLC standard` section linking the audit; ADR 0015 records
  the rationale and the pairing with NIST SP 800-53 (cybersecurity),
  OWASP ASVS (#112), and SLSA / cosign / SBOM (#109 / #110 / #111).
  `scripts/verify-standards.sh` gates the new section.
- **pytest-cov line+branch coverage gate with a ratcheting floor**. CI
  now fails if total coverage of `src/` drops below the
  `--cov-fail-under=<N>` threshold configured in `pyproject.toml`
  (initial floor 74; baseline TOTAL was 74.77% on merge). The bump
  procedure is documented in `CONTRIBUTING.md` § "Coverage". Integration
  and `--fast` test modes run with `--no-cov`; the floor is measured
  against `--unit` only. Closes
  [#37](https://github.com/aidanns/agent-auth/issues/37).
- **mypy + pyright type-checking**. Both run in CI under
  `task typecheck` (new `.github/workflows/typecheck.yml`). `pyproject.toml`
  declares `[tool.mypy]` with `strict = true` as the default;
  `pyrightconfig.json` uses `typeCheckingMode: "strict"`. Modules that
  failed at foundation time are relaxed per-module and tracked for
  ratcheting in [#145](https://github.com/aidanns/agent-auth/issues/145)
  (agent_auth),
  [#146](https://github.com/aidanns/agent-auth/issues/146)
  (things_bridge),
  [#147](https://github.com/aidanns/agent-auth/issues/147)
  (things_cli / things_client_common / things_models), and
  [#148](https://github.com/aidanns/agent-auth/issues/148) (tests).
  Closes [#48](https://github.com/aidanns/agent-auth/issues/48).
- **OpenTelemetry semantic conventions adopted for observability naming.** New
  ADR 0017 pins the project to OTel semconv
  [v1.40.0](https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.40.0)
  for HTTP-server metric names and HTTP-attribute audit-log keys. A new
  `## Observability` section in `design/DESIGN.md` documents the mapping and
  the domain fields that keep their existing names. No code changes; this
  lands the standard that #26 (metrics endpoint), #20 (audit schema pinning),
  and #33 (observability design) build on.
- **Graceful SIGTERM / SIGINT handling in `agent-auth serve` and
  `things-bridge serve`.** Both entrypoints now install signal handlers that
  stop accepting new connections, drain in-flight requests within
  `shutdown_deadline_seconds` (default 5s, configurable per service), and
  checkpoint the `agent-auth` SQLite WAL before exiting 0. A daemon
  watchdog `os._exit(1)`s if drain exceeds the deadline so a hung request
  cannot hold the process past its container's `stop_grace_period`. See
  ADR 0018. Closes
  [#154](https://github.com/aidanns/agent-auth/issues/154).

### Changed

- `lefthook.yml` consolidates the per-language formatter checks (mdformat,
  ruff format, shellcheck, shfmt, taplo) under a single
  `treefmt --no-cache --fail-on-change` invocation; `ruff check` and
  `keep-sorted` remain as dedicated commands
  ([#42](https://github.com/aidanns/agent-auth/issues/42)).
- `agent-auth serve` / `things-bridge serve` now print the OS-assigned
  port on their `listening on ...` startup line when configured with
  `port: 0`, instead of echoing the literal `0`
  ([#163](https://github.com/aidanns/agent-auth/issues/163)).
- **Token management HTTP routes moved under `/v1/`.**
  `POST /agent-auth/token/{create,modify,revoke,rotate}` and
  `GET /agent-auth/token/list` are now served at `/agent-auth/v1/token/...`.
  Completes the `/v1/` API namespace migration so every non-health route is
  versioned (enforced by `scripts/verify-standards.sh`).
- `setup-toolchain` release-binary installs now go through a shared
  `scripts/ci/fetch-release-asset.sh` helper (curl + auth + sha256 verify)
  rather than open-coding the same block in 7 steps. Retry flags retuned
  to `--retry 5 --retry-max-time 60 --retry-all-errors` (no explicit
  `--retry-delay`) so curl honours `Retry-After` and exponential backoff
  on 429s/5xx. `Install systems-engineering` stays inline (Contents API
  with a custom Accept header and no pinned sha256) but picks up the
  same retry retune. Part 3 of the follow-up (parallelise downloads) is
  tracked separately
  ([#165](https://github.com/aidanns/agent-auth/issues/165)).
- `setup-toolchain` release-binary installs now run the 7 downloads
  concurrently in a single `Install release binaries` step
  (`fetch-release-asset.sh ... &` plus a per-PID `wait` loop that
  fails fast on any curl / sha256 error). Extract + install + version
  echo stays serial with `::group::` markers for per-tool log
  readability. Trims composite-action wall-time on every CI job.
  Completes the #165 follow-up sequenced in
  [#168](https://github.com/aidanns/agent-auth/issues/168).
- **Release-adjacent GitHub Actions pinned to commit SHAs.**
  `release-please.yml`, `release-publish.yml`, `reuse.yml`, and
  `.github/actions/setup-toolchain/action.yml` now reference every
  third-party action by full commit SHA with a trailing `# vX` comment
  (e.g. `actions/checkout@de0fac2... # v6`). Read-only workflows
  (`check.yml`, `test.yml`, `verify-*.yml`, `typecheck.yml`,
  `security.yml`) stay on floating-major tags. Policy documented in
  `.claude/instructions/tooling-and-ci.md` "Pin release-affecting GitHub
  Actions to commit SHAs"; Dependabot's existing `github-actions`
  ecosystem entry (minor/patch grouped, majors individual) keeps the
  pins refreshed. Closes
  [#127](https://github.com/aidanns/agent-auth/issues/127).

### Fixed

- `setup-toolchain` composite action fetches the `systems-engineering`
  installer through the authenticated GitHub Contents API (when
  `github-token` is provided) and retries transient failures with backoff,
  eliminating flakes where 6 parallel CI jobs tripped the unauthenticated
  `raw.githubusercontent.com` per-IP rate limit
  ([#155](https://github.com/aidanns/agent-auth/issues/155)).
- `setup-toolchain` release-binary installs (shellcheck, shfmt, ruff, taplo,
  keep-sorted, ripsecrets, treefmt) now download with the same
  `--retry 2 --retry-delay 2 --retry-all-errors` flags and authenticated
  `Authorization: Bearer ${github-token}` header used by the
  systems-engineering step, absorbing transient GitHub-release-download
  flakes and lifting the per-IP anonymous rate limit
  ([#159](https://github.com/aidanns/agent-auth/issues/159)).

## [0.1.0] - 2026-04-19

### Added

- **agent-auth server and CLI** — HTTP validation server (`agent-auth serve`) with full
  token lifecycle management: create, list, modify, revoke, rotate. HMAC-SHA256 signed
  tokens with AES-256-GCM field encryption and signing key held in the system keyring.
  Three-tier scope model (allow / prompt / deny), JIT approval via pluggable notification
  plugin, token families with refresh-token reuse detection, and audit logging.
- **things-bridge** — HTTP bridge server (`things-bridge serve`) that delegates token
  validation to agent-auth and exposes read-only Things 3 endpoints under
  `/things-bridge/`. The bridge contains no Things 3 logic; it shells out to a configured
  Things-client CLI per request.
- **things-client-cli-applescript** — Standalone read-only CLI that talks to Things 3 via
  `osascript` on macOS. Emits JSON on stdout; usable independently of things-bridge for
  local debugging.
- **things-cli** — Thin HTTP client for things-bridge that auto-refreshes/reissues tokens
  via agent-auth. Stores credentials in the system keyring (falls back to a
  `~/.config/things-cli/credentials.yaml` file when no keyring backend is available).

### Changed

- **`task release` auto-derives the next version.** Run `task release` with no
  argument and the script walks Conventional Commits since the last `v*` tag to
  pick a major / minor / patch bump (BREAKING → major, `feat:` → minor,
  `fix:` → patch). Pass `task release -- X.Y.Z` to override. While the current
  tag is in the `0.x` range the API is not considered stable (SemVer 2.0.0 §4),
  so a detected major bump is demoted to a minor bump; pass an explicit
  `task release -- 1.0.0` to graduate.
- **`task release -- -y` skips the confirmation prompt** so the release can
  run hands-off (e.g. `task release -- -y 1.2.3`). The signed-tag step still
  needs your signing key; see `CONTRIBUTING.md` § "Non-interactive signing
  for `task release`" for gpg-agent / ssh-agent pre-warm instructions.

[0.1.0]: https://github.com/aidanns/agent-auth/releases/tag/v0.1.0
[unreleased]: https://github.com/aidanns/agent-auth/compare/v0.1.0...HEAD
