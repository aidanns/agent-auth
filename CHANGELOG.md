<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
