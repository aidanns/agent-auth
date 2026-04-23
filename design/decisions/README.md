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
  — keyless cosign signatures and per-artefact SPDX SBOMs on every release; REUSE per-file licensing across the source tree. Autorelease-driver choice superseded by ADR 0026.
- [ADR 0017 — Adopt OpenTelemetry semantic conventions for metrics and logs](0017-opentelemetry-semantic-conventions.md)
  — HTTP-server metric and log attribute names follow OTel semconv v1.40.0; domain fields keep their existing names.
- [ADR 0018 — Handle SIGTERM gracefully in `agent-auth` and `things-bridge`](0018-graceful-shutdown.md)
  — SIGTERM/SIGINT drain in-flight requests within `shutdown_deadline_seconds` (default 5s) before a watchdog force-exits via `os._exit(1)`.
- [ADR 0019 — Adopt OWASP ASVS v5 as the application security verification standard](0019-owasp-asvs-application-security-standard.md)
  — application-layer companion to NIST SP 800-53 and NIST SSDF at target Level 2; per-chapter conformance tracked in `design/ASVS.md`.
- [ADR 0020 — SLSA Build Level 3 provenance via slsa-github-generator](0020-slsa-build-provenance.md)
  — tag-triggered `release-publish.yml` attaches `multiple.intoto.jsonl` in-toto attestations to every release; verification via `slsa-verifier verify-artifact`.
- [ADR 0021 — Mutation testing on security-critical modules](0021-mutation-testing-security-critical.md)
  — nightly mutmut pass on tokens/crypto/keys/scopes/store gated by a ratcheting score floor; `scripts/verify-standards.sh` enforces `[tool.mutmut]` config and scheduled workflow stay present.
- [ADR 0022 — Defer application-layer rate limiting; rely on loopback-only bind and bounded request bodies](0022-rate-limiting-posture.md)
  — *superseded by ADR 0027.* Originally deferred rate limiting on loopback-only grounds; TLS-for-devcontainer (ADR 0025) invalidated the loopback premise.
- [ADR 0023 — Deepen `/things-bridge/health` to verify the Things-client binary is resolvable](0023-things-bridge-health-depth.md)
  — /health now returns 503 `{"status":"unhealthy"}` when `things_client_command[0]` fails PATH resolution; cached for 30s to keep the probe cheap. agent-auth reachability is covered implicitly by the probe-authorization call.
- [ADR 0024 — Single-source audit trail at agent-auth with a cross-service resource envelope](0024-audit-log-shared-envelope.md)
  — keep things-bridge audit-free (authz traces come via agent-auth); add OTel `service.name` / `service.version` to every audit entry so a future second emitter drops in with no schema churn; mark HTTP-attribute fields as reserved until emission lands.
- [ADR 0025 — Optional in-process TLS listener on agent-auth and things-bridge](0025-tls-for-devcontainer-host-traffic.md)
  — close SC-8 for devcontainer-to-host traffic via a config-gated `ssl.SSLContext` wrap of the server socket (TLS 1.2+); plaintext stays the default for the loopback-only single-host deployment.
- [ADR 0026 — Migrate autorelease driver from Release Please to semantic-release](0026-semantic-release-autorelease.md)
  — semantic-release runs on every push to `main` and cuts a release immediately on any qualifying Conventional Commit; PR-merge review replaces the Release Please release-PR guardrail; setuptools-scm remains the runtime version source.
- [ADR 0027 — In-memory per-token-family rate limiting](0027-rate-limiting-implementation.md)
  — supersedes ADR 0022. Every authenticated endpoint consumes from a token-bucket keyed on `family_id`; 429 `{"error":"rate_limited"}` with `Retry-After` on exhaustion. Default 600 req/min; set `rate_limit_per_minute: 0` to opt back into ADR 0022's deferral.
