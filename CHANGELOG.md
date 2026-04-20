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

### Changed

- **Token management HTTP routes moved under `/v1/`.**
  `POST /agent-auth/token/{create,modify,revoke,rotate}` and
  `GET /agent-auth/token/list` are now served at `/agent-auth/v1/token/...`.
  Completes the `/v1/` API namespace migration so every non-health route is
  versioned (enforced by `scripts/verify-standards.sh`).

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
