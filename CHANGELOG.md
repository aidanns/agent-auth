# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **`task release` auto-derives the next version.** Run `task release` with no
  argument and the script walks Conventional Commits since the last `v*` tag to
  pick a major / minor / patch bump (BREAKING → major, `feat:` → minor,
  `fix:` → patch). Pass `task release -- X.Y.Z` to override.

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

[0.1.0]: https://github.com/aidanns/agent-auth/releases/tag/v0.1.0
[unreleased]: https://github.com/aidanns/agent-auth/compare/v0.1.0...HEAD
