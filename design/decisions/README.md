<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Architecture Decision Records

Short records of the significant design decisions made on this project.
Each ADR captures the forces behind a decision (Context), the decision
itself, and its consequences, so the rationale survives beyond commit
messages. See [`.claude/instructions/design.md`](../../.claude/instructions/design.md)
for the standard that mandates them and
[`TEMPLATE.md`](TEMPLATE.md) for the skeleton new ADRs should follow.

The regression check in
[`scripts/verify-standards.sh`](../../scripts/verify-standards.sh)
enforces that every file in this directory (other than `README.md` and
`TEMPLATE.md`) contains Context / Decision / Consequences sections and
is linked from this index.

## Index

- [ADR 0001 — Client-level fake for things-bridge](0001-things-client-fake.md)
  — superseded by 0003; kept for history.
- [ADR 0002 — Batch AppleScript property reads in `list_todos`](0002-list-todos-batched-applescript.md)
  — performance fix for unfiltered todo listing on a real Things 3 database.
- [ADR 0003 — Split Things clients into sibling CLIs](0003-things-client-cli-split.md)
  — production and fake Things clients ship as separate `things-client-cli-*` binaries.
- [ADR 0004 — Docker-based HTTP integration tests](0004-docker-integration-tests.md)
  — per-test Compose project driving `agent-auth` through its public HTTP surface.
- [ADR 0005 — Per-service Docker integration tests for the things-\* surface](0005-things-services-docker-tests.md)
  — extends the ADR 0004 pattern to `things-bridge`, `things-cli`, and `things-client-cli-applescript`.
- [ADR 0006 — Token format](0006-token-format.md)
  — `aa_<id>_<sig>` / `rt_<id>_<sig>` with HMAC-SHA256 over the typed ID.
- [ADR 0007 — SQLite with field-level AES-256-GCM encryption](0007-sqlite-field-level-encryption.md)
  — encrypt sensitive columns only; keep IDs and timestamps queryable.
- [ADR 0008 — System keyring for signing and encryption keys](0008-system-keyring-for-key-material.md)
  — key material lives in Keychain / libsecret, never on disk.
- [ADR 0009 — CLI / server split with a single trust boundary](0009-cli-server-split.md)
  — `agent-auth serve` owns the keyring; the CLI is a thin client.
- [ADR 0010 — Three-tier scope model with JIT approval](0010-three-tier-scope-model.md)
  — allow / prompt / deny tiers and a configurable approval plugin.
- [ADR 0011 — Refresh-token reuse triggers family revocation](0011-refresh-token-reuse-family-revocation.md)
  — single-use refresh tokens with reuse detection and a JIT re-issuance path.
- [ADR 0012 — XDG path layout](0012-xdg-path-layout.md)
  — config under `$XDG_CONFIG_HOME`, data under `$XDG_DATA_HOME`, state under `$XDG_STATE_HOME`.
- [ADR 0013 — AppleScript-based Things bridge](0013-applescript-things-bridge.md)
  — accept in-process AppleScript for now; out-of-process split is staged via the `ThingsClient` subprocess contract.
- [ADR 0014 — Management endpoints require a management bearer token](0014-management-endpoint-auth.md)
  — `agent-auth:manage=allow` scope gates create/list/modify/revoke/rotate; bootstrapped at server startup into the OS keyring.
- [ADR 0015 — Adopt NIST SSDF (SP 800-218) as the SDLC standard](0015-nist-ssdf-sdlc-standard.md)
  — SSDF is the SDLC-practices companion to the existing NIST SP 800-53 cybersecurity standard; conformance tracked in `design/SSDF.md`.
- [ADR 0016 — Release supply chain: Release Please + keyless cosign + SPDX SBOM + REUSE](0016-release-supply-chain.md)
  — autorelease via Release Please; keyless cosign signatures and per-artefact SPDX SBOMs on every release; REUSE per-file licensing across the source tree.
- [ADR 0017 — Adopt OpenTelemetry semantic conventions for metrics and logs](0017-opentelemetry-semantic-conventions.md)
  — HTTP-server metric and log attribute names follow OTel semconv v1.40.0; domain fields keep their existing names.
- [ADR 0018 — Handle SIGTERM gracefully in `agent-auth` and `things-bridge`](0018-graceful-shutdown.md)
  — SIGTERM/SIGINT drain in-flight requests within `shutdown_deadline_seconds` (default 5s) before a watchdog force-exits via `os._exit(1)`.
