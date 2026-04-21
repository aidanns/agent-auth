<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ASVS Conformance

agent-auth adopts [OWASP Application Security Verification Standard
(ASVS) v5](https://owasp.org/www-project-application-security-verification-standard/)
as its reference standard for application-layer verification,
targeting **Level 2 (L2)**. ASVS sits alongside three companion
standards:

- [NIST SP 800-53 Rev 5](../SECURITY.md#cybersecurity-standard) —
  system-level cybersecurity controls (access control, audit,
  authentication, communications protection, system integrity).
- [NIST SP 800-218 (SSDF)](SSDF.md) — SDLC-side practices that
  produce the software (PO / PS / PW / RV).
- Supply-chain artefacts — SLSA provenance
  ([#109](https://github.com/aidanns/agent-auth/issues/109)),
  Sigstore / cosign signing (ADR 0016), SPDX SBOM (ADR 0016), and
  OpenSSF Scorecard
  ([#108](https://github.com/aidanns/agent-auth/issues/108)).

NIST SP 800-53 specifies **what the running system does** at
family granularity; SSDF specifies **what practices the project
follows** to build the software; ASVS specifies **what the
application surface verifies** on behalf of its clients. This
document records agent-auth's per-chapter conformance against
ASVS v5, so implementation plans can walk the application
standard in the same way they walk SP 800-53 controls and SSDF
practices today.

## Rationale for selecting ASVS

- **Application-scoped.** ASVS is written for application code
  that authenticates, authorises, and protects data in transit
  and at rest. That matches the agent-auth / things-bridge
  surface exactly. Broader standards (NIST SP 800-53, ISO 27001)
  are organisational; narrower ones (PCI-DSS, HIPAA) are
  vertical-specific to industries agent-auth is not in.
- **Tiered and walkable.** ASVS's L1 / L2 / L3 levels let a solo
  project target a realistic bar (L2: "most applications") and
  make the verification items grep-able against source code,
  ADRs, and threat-model rows rather than abstract principles.
- **Pairs with the standards already adopted.** ASVS was named
  as the application-layer companion in
  [ADR 0015](decisions/0015-nist-ssdf-sdlc-standard.md) when
  SSDF was adopted. This document discharges that deferred
  selection; the rationale is expanded in
  [ADR 0019](decisions/0019-owasp-asvs-application-security-standard.md).

## Target level: L2

L2 is ASVS's "most applications" bar — the default for any
application that handles non-trivial user data or credentials.
L1 is explicitly insufficient for anything that handles
authentication material, and agent-auth *is* the authentication
material. L3 assumes high-assurance / regulated contexts
(finance, healthcare, critical infrastructure, military) where
every control is independently verified, every data flow is
threat-modelled against a motivated adversary with insider
access, and supply-chain provenance is mandatory at every step.
L3 does not fit a solo-maintained, local-only, single-user
project.

Where a specific L2 requirement is stricter than the current
implementation, the row below is marked **Partial** and links
the issue tracking the gap — rather than silently downgrading
to L1.

## Conformance status legend

- **Implemented** — a committed artefact satisfies the chapter's
  L2 concerns today.
- **Partial** — chapter is partially satisfied with a known gap;
  the linked issue tracks the remainder.
- **Planned** — chapter is in scope but work has not started;
  the linked issue tracks it.
- **Not applicable** — chapter's subject matter is absent from
  the project (e.g. no web frontend, no OAuth flow, no WebRTC).
  The rationale is recorded in-line.

## Per-chapter conformance

| Chapter                                   | Summary                                                                                                                    | Scope          | Conformance    | Evidence / gap                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V1 — Encoding and Sanitization            | Prevent injection by context-appropriate encoding / sanitisation at each output sink.                                      | In scope       | Implemented    | things-bridge constructs subprocess argv from schema-validated parameters, never from raw client input; no string interpolation into shell (`src/things_bridge/server.py`). SQL uses parameterised statements only (`src/agent_auth/store.py`). No HTML / JS / XML output sinks exist (no web UI). See also `SECURITY.md` STRIDE row *"things-bridge constructs arbitrary argv passed to things-client CLI"*.                                                                                                                                                                                                                                                                         |
| V2 — Validation and Business Logic        | Validate the shape, type, range, and business intent of every input before acting on it.                                   | In scope       | Implemented    | Every HTTP handler schema-validates request bodies before dispatch; invalid payloads return `400 validation_failed` per the public error taxonomy (`src/agent_auth/errors.py`, `src/things_bridge/errors.py`). Request bodies are capped at 1 MiB (`MAX_BODY_SIZE` in `src/agent_auth/server.py`, `src/things_bridge/server.py`). Business-logic rules (scope tier resolution, refresh-token reuse detection, family revocation) are enforced on the server, not the client.                                                                                                                                                                                                          |
| V3 — Web Frontend Security                | CSP, frame protection, CSRF, clickjacking, storage of sensitive data in browsers.                                          | Not applicable | Not applicable | agent-auth exposes no browser-facing UI. The HTTP surface serves JSON to programmatic clients (things-cli, things-bridge, `agent-auth` CLI). No cookies, no `<form>` targets, no JavaScript is served. If a browser-facing management UI is added later, this chapter becomes in scope and must be walked in the same PR.                                                                                                                                                                                                                                                                                                                                                             |
| V4 — API and Web Service                  | API input handling, method validation, content-type enforcement, rate limiting, and denial-of-service protections.         | In scope       | Partial        | Handlers reject unexpected methods with `405`; `Content-Type` is checked before parsing; request bodies are capped at 1 MiB. Rate limiting is not yet enforced — tracked in [#102](https://github.com/aidanns/agent-auth/issues/102). OpenAPI specs for both services tracked in [#117](https://github.com/aidanns/agent-auth/issues/117).                                                                                                                                                                                                                                                                                                                                            |
| V5 — File Handling                        | Safe upload / download / extraction, path traversal, content-type enforcement for file ingest.                             | Not applicable | Not applicable | agent-auth does not accept file uploads from clients; there is no user-supplied-file sink. Config files (`config.yaml`) are operator-owned and read on startup under a known XDG path ([ADR 0012](decisions/0012-xdg-path-layout.md)); the plugin and Things-client CLI paths are operator-configured executables, not user-uploaded artefacts.                                                                                                                                                                                                                                                                                                                                       |
| V6 — Authentication                       | Verification of claimed identity: credential storage, strength, rotation, lockout, MFA, credential-recovery flow.          | In scope       | Implemented    | Callers authenticate with bearer tokens of the form `aa_<family-id>_<sig>` ([ADR 0006](decisions/0006-token-format.md)); signature is HMAC-SHA256 over the typed prefix + family id. Management endpoints require a bearer token whose family carries `agent-auth:manage=allow` ([ADR 0014](decisions/0014-management-endpoint-auth.md)). Signing key is generated on first run and stored in the OS keyring ([ADR 0008](decisions/0008-system-keyring-for-key-material.md)); keys are not rotated automatically (documented gap in `SECURITY.md` *Key handling*). Credential-recovery mechanism is re-bootstrapping the management token family from the keyring-held refresh token. |
| V7 — Session Management                   | Session issuance, expiry, revocation, rotation, and reuse-detection for stateful or stateless sessions.                    | In scope       | Implemented    | Access tokens carry an expiry; the server rejects expired tokens with `401 token_expired` ([ADR 0006](decisions/0006-token-format.md)). Refresh-token reuse triggers family-wide revocation ([ADR 0011](decisions/0011-refresh-token-reuse-family-revocation.md)). Explicit revocation via `agent-auth token revoke <family>`. Rotation via `/v1/token/rotate`. Family-wide revocation path is the STRIDE mitigation for *"Replay of a revoked token"*.                                                                                                                                                                                                                               |
| V8 — Authorization                        | Access control: least privilege, deny-by-default, server-side enforcement, per-request authorization.                      | In scope       | Implemented    | Scope model has three tiers (`allow` / `prompt` / `deny`) with deny-by-default ([ADR 0010](decisions/0010-three-tier-scope-model.md)); every `/validate` call re-checks scope tier server-side — clients cannot self-elevate. `prompt`-tier scopes require real-time human approval via the JIT plugin. things-bridge *always* re-validates with agent-auth per request (`src/things_bridge/authz.py`); it never caches authorisation decisions.                                                                                                                                                                                                                                      |
| V9 — Self-contained Tokens                | Integrity and confidentiality of stateless tokens (JWT or equivalent); binding to context; revocation-awareness.           | In scope       | Implemented    | Tokens are HMAC-SHA256 signed over `<prefix> + <family-id>` ([ADR 0006](decisions/0006-token-format.md)); prefix (`aa_` vs `rt_`) is part of the HMAC input — cross-type substitution fails verification. Tokens are *not* JWTs: they carry no client-visible claims, only a family id. Authoritative data (scopes, expiry, revocation) lives in `tokens.db`; every `/validate` call re-reads the authoritative record, so the "self-contained token" threats around stale claims do not apply.                                                                                                                                                                                       |
| V10 — OAuth and OIDC                      | OAuth 2.x / OIDC authorization-server and relying-party controls.                                                          | Not applicable | Not applicable | agent-auth does not implement OAuth or OIDC. The token scheme is a proprietary bearer format documented in [ADR 0006](decisions/0006-token-format.md) and the public API spec. No `Authorization Code`, `Client Credentials`, `Device Authorization`, or `Implicit` flows exist. If an OAuth surface is added later (e.g. to front agent-auth with a standards-compliant IdP), this chapter becomes in scope.                                                                                                                                                                                                                                                                         |
| V11 — Cryptography                        | Approved algorithms, key strength, key lifecycle, random-number generation, constant-time comparison.                      | In scope       | Partial        | HMAC-SHA256 and AES-256-GCM are both on ASVS-approved algorithm lists at L2. Signing-key material is generated with `secrets.token_bytes(32)` and lives in the OS keyring ([ADR 0008](decisions/0008-system-keyring-for-key-material.md)); never written to disk. Signatures are compared with `hmac.compare_digest` (`src/agent_auth/tokens.py`). **Gap:** automatic key rotation is not implemented — `SECURITY.md` *Key handling* documents the manual rotation procedure. Audit-log cryptographic chaining tracked in [#103](https://github.com/aidanns/agent-auth/issues/103).                                                                                                   |
| V12 — Secure Communications               | Transport-layer confidentiality / integrity (TLS), certificate validation, protocol hardening.                             | In scope       | Partial        | All services bind to `127.0.0.1` by default (`src/agent_auth/config.py`, `src/things_bridge/config.py`) — the STRIDE threat model documents loopback-only deployment as the current mitigation for eavesdropping. **Gap:** TLS between the devcontainer and host for devcontainer-to-host traffic is not implemented — tracked in [#101](https://github.com/aidanns/agent-auth/issues/101). This is the same gap documented under NIST SP 800-53 SC-8 in `SECURITY.md`.                                                                                                                                                                                                               |
| V13 — Configuration                       | Secure defaults, secret handling, separation of build / run configuration, hardened deployment configuration.              | In scope       | Implemented    | All services bind to `127.0.0.1` by default; `deny` is the default scope tier; request-body size is capped by default; plugin trust is opt-in via `config.yaml`. XDG paths ([ADR 0012](decisions/0012-xdg-path-layout.md)) separate config / data / state. Secrets (signing key, encryption key, management refresh token) live in the OS keyring, not config files. YAML configuration supersedes the earlier JSON format ([#24](https://github.com/aidanns/agent-auth/issues/24)). Per-change configuration review is codified in `.claude/instructions/service-design.md`.                                                                                                         |
| V14 — Data Protection                     | Protection of sensitive data at rest and during processing; minimisation, erasure, memory handling.                        | In scope       | Implemented    | Sensitive columns in `tokens.db` are AES-256-GCM encrypted at rest ([ADR 0007](decisions/0007-sqlite-field-level-encryption.md)); plaintext is only held in-process after decryption (`src/agent_auth/crypto.py`). Token values (`aa_...` / `rt_...`) are never logged — audit records reference family ids only. Access tokens are short-lived (default 900 s) so leaked plaintext ages out quickly.                                                                                                                                                                                                                                                                                 |
| V15 — Secure Coding and Architecture      | Trusted / untrusted boundary enforcement, supply-chain hygiene, architectural security invariants.                         | In scope       | Partial        | Trust boundaries are documented in `SECURITY.md` *Trust boundaries*; agent-auth is the sole trust root for signing material. Supply-chain controls land via [ADR 0016](decisions/0016-release-supply-chain.md) — keyless cosign signing and SPDX SBOM on every release. **Gap:** the JIT-approval plugin runs in-process via `importlib.import_module`, meaning a malicious plugin would execute inside the signing-key-bearing process. Out-of-process migration tracked in [#6](https://github.com/aidanns/agent-auth/issues/6).                                                                                                                                                    |
| V16 — Security Logging and Error Handling | Comprehensive security events logged; errors do not leak sensitive data; logs are tamper-evident and retention is managed. | In scope       | Partial        | `src/agent_auth/audit.py` emits a JSON-lines audit entry for every token lifecycle event and authorization decision, with a pinned `schema_version` field ([#20](https://github.com/aidanns/agent-auth/issues/20)). Token values are never logged. Error responses follow the documented error taxonomy and do not leak internal state. **Gap:** audit log is append-only at the filesystem level but not cryptographically tamper-evident — chaining tracked in [#103](https://github.com/aidanns/agent-auth/issues/103); cross-service schema unification in [#100](https://github.com/aidanns/agent-auth/issues/100).                                                              |
| V17 — WebRTC                              | Peer-to-peer media / data-channel security.                                                                                | Not applicable | Not applicable | agent-auth uses only unicast HTTP; no WebRTC peer connections, ICE servers, SRTP streams, or data channels exist.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

## Per-plan checklist

`.claude/instructions/plan-template.md` *Cybersecurity standard
compliance* step is amended implicitly by this document: plans
that touch an in-scope ASVS chapter should walk the chapter
alongside the NIST SP 800-53 control family already required.
When a plan introduces a new category of application-surface work
(e.g. a new HTTP endpoint, a new credential type, a new encrypted
field), update this document in the same PR rather than deferring
it.

## Consistency with NIST SP 800-53

The NIST SP 800-53 Rev 5 families named as in-scope in
[`SECURITY.md`](../SECURITY.md#cybersecurity-standard) map onto
ASVS chapters as follows. No conflicts exist between the two;
ASVS decomposes the same concerns at application-surface
granularity.

| NIST SP 800-53 family                     | ASVS chapter(s)                                                                                           |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| AC — Access Control                       | V8 Authorization                                                                                          |
| AU — Audit and Accountability             | V16 Security Logging and Error Handling                                                                   |
| IA — Identification and Authentication    | V6 Authentication, V7 Session Management, V9 Self-contained Tokens                                        |
| SC — System and Communications Protection | V11 Cryptography, V12 Secure Communications, V14 Data Protection                                          |
| SI — System and Information Integrity     | V1 Encoding and Sanitization, V2 Validation and Business Logic, V4 API and Web Service, V13 Configuration |

Chapters not paired above (V3, V5, V10, V15, V17) are either
application-surface-only (V15 is covered by SSDF PS / PW instead
of a SP 800-53 family) or scoped out of this project per the
table above.

## Follow-up issues

Gaps identified by this audit are tracked via GitHub issues
linked in the table above. Each linked issue is already filed;
this audit does not open new issues beyond the chapters where a
gap was already known. Issues filed as part of
[#112](https://github.com/aidanns/agent-auth/issues/112):

- [#6](https://github.com/aidanns/agent-auth/issues/6) —
  V15 out-of-process plugin boundary.
- [#100](https://github.com/aidanns/agent-auth/issues/100) —
  V16 unified audit schema across services.
- [#101](https://github.com/aidanns/agent-auth/issues/101) —
  V12 TLS for devcontainer-to-host traffic.
- [#102](https://github.com/aidanns/agent-auth/issues/102) —
  V4 rate limiting.
- [#103](https://github.com/aidanns/agent-auth/issues/103) —
  V11 / V16 audit-log cryptographic chaining.
- [#117](https://github.com/aidanns/agent-auth/issues/117) —
  V4 OpenAPI specification publication.
