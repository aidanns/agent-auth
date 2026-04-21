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

### Changed

- `lefthook.yml` consolidates the per-language formatter checks (mdformat,
  ruff format, shellcheck, shfmt, taplo) under a single
  `treefmt --no-cache --fail-on-change` invocation; `ruff check` and
  `keep-sorted` remain as dedicated commands
  ([#42](https://github.com/aidanns/agent-auth/issues/42)).
- **Token management HTTP routes moved under `/v1/`.**
  `POST /agent-auth/token/{create,modify,revoke,rotate}` and
  `GET /agent-auth/token/list` are now served at `/agent-auth/v1/token/...`.
  Completes the `/v1/` API namespace migration so every non-health route is
  versioned (enforced by `scripts/verify-standards.sh`).

### Fixed

- `setup-toolchain` composite action fetches the `systems-engineering`
  installer through the authenticated GitHub Contents API (when
  `github-token` is provided) and retries transient failures with backoff,
  eliminating flakes where 6 parallel CI jobs tripped the unauthenticated
  `raw.githubusercontent.com` per-IP rate limit
  ([#155](https://github.com/aidanns/agent-auth/issues/155)).

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
