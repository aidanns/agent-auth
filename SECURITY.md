# Security

## Trust boundaries

agent-auth is a **local, single-user** authorization system. All components
bind to `127.0.0.1` by default; they are not designed for multi-tenant or
network-exposed deployment.

```
┌──────────────────────┐            ┌─────────────────────────────────────────────┐
│  Devcontainer        │            │  Host machine                               │
│                      │            │                                             │
│  things-cli ──────HTTP────────────▶  things-bridge ──────────────▶ Things 3     │
│              │       │            │    │                                        │
│              │       │            │    │ HTTP (validate, approve)               │
│              │       │            │    ▼                                        │
│              └────HTTP────────────▶  agent-auth                                  │
│                      │            │    ├─ tokens.db (SQLite + AES-256-GCM)      │
│                      │            │    └─ signing key (system keyring)          │
└──────────────────────┘            └─────────────────────────────────────────────┘
```

Trust boundary decisions:

- **agent-auth** is the trust root. Only it holds the signing key and token
  store. All other components validate tokens by calling agent-auth's HTTP API;
  they never access the store or key directly.
- **things-bridge** trusts agent-auth's validation response and the configured
  Things-client CLI's stdout. It does not trust the bearer token it receives
  from things-cli — it always re-validates with agent-auth before acting.
- **things-cli** trusts agent-auth for token issuance and refresh, and
  things-bridge for data responses.
- **things-client-cli-applescript** runs on the host with the user's macOS
  Automation permission. It receives argv from things-bridge and emits JSON on
  stdout; its only trust assumption is that the invoking process (things-bridge)
  is legitimate. No authentication between bridge and client CLI.
- **Notification plugin** (JIT approval): currently loaded in-process in the
  agent-auth server via `importlib.import_module`, which means a malicious
  plugin would run inside the process that holds the signing and encryption keys.
  Migration to an out-of-process plugin boundary is tracked in
  [#6](https://github.com/aidanns/agent-auth/issues/6).

## Token management endpoints

The management endpoints (`POST /agent-auth/token/create`,
`GET /agent-auth/token/list`, `POST /agent-auth/token/modify`,
`POST /agent-auth/token/revoke`, `POST /agent-auth/token/rotate`) require
`Authorization: Bearer <token>` where the token's family carries
`agent-auth:manage=allow` in its scopes.

On first startup the server creates this management token family directly via
the store and stores the refresh token in the OS keyring. Operators retrieve
it with `agent-auth management-token show` and exchange it for an access
token via `POST /agent-auth/token/refresh`. External clients must refresh
before each management session (access tokens expire after 900 s by default).

The `agent-auth:manage` scope is reserved. The management token family is
excluded from `GET /token/list` responses. If the management family is rotated
or revoked, the server recreates it automatically on the next restart. See
[ADR 0014](design/decisions/0014-management-endpoint-auth.md) for the full
rationale.

## Threat model

Each threat is assessed using a qualitative risk matrix following
**NIST SP 800-30 Rev 1** guidance. **Impact** and **Likelihood** are each rated
High, Medium, or Low independently; the overall **Rating** is their product
(High × Low = Medium, High × Medium = High, etc.). Each mitigation notes whether
it targets Impact, Likelihood, or both, and links to the implementing function in
the [functional decomposition](design/functional_decomposition.yaml) or to the
tracking issue.

### Spoofing

| Threat                                                             | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------ | ------ | ---------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Forged token presented to agent-auth `/validate`                   | High   | Low        | Medium | HMAC-SHA256 signature over `prefix + token-id` prevents forgery without the signing key. Targets: **likelihood**. Implemented: [Verify Token Signature](design/functional_decomposition.yaml#L24), [Load Signing Key](design/functional_decomposition.yaml#L51) |
| Cross-type token substitution (access token used as refresh token) | Medium | Low        | Low    | The token prefix (`aa_` vs `rt_`) is included in the HMAC input; a valid access-token signature does not verify for the refresh-token type. Targets: **likelihood**. Implemented: [Verify Token Signature](design/functional_decomposition.yaml#L24)            |
| Rogue process binding to 127.0.0.1:9100 before agent-auth          | High   | Low        | Medium | Mitigated by user being the sole operator of the host machine. No cryptographic protection against a co-located rogue process winning the bind race. Targets: **neither** (accepted risk for a local-only single-user deployment).                              |

### Tampering

| Threat                                               | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------- | ------ | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Direct modification of `tokens.db`                   | High   | Low        | Medium | Scope and HMAC-signature fields are AES-256-GCM encrypted at rest; modification without the key produces authentication-tag failures on read. Targets: **impact** (modification detected, scopes unreadable). Implemented: [Encrypt Field](design/functional_decomposition.yaml#L69), [Decrypt Field](design/functional_decomposition.yaml#L72), [Query Tokens](design/functional_decomposition.yaml#L67)            |
| Replay of a revoked token                            | High   | Low        | Medium | Revocation writes `revoked_at` to the token record; validation checks `revoked_at IS NULL` before accepting. Reuse of a refresh token triggers family-wide revocation. Targets: **likelihood**. Implemented: [Mark Family Revoked](design/functional_decomposition.yaml#L65), [Detect Refresh Token Reuse](design/functional_decomposition.yaml#L19), [Check Token Expiry](design/functional_decomposition.yaml#L26) |
| Tampering with the signing key in the system keyring | High   | Low        | Medium | Requires OS-level access to the keyring (macOS Keychain or libsecret). If the key is replaced, all previously issued tokens become invalid on next validation. Targets: **likelihood** (OS keyring restricts access). Implemented: [Load Signing Key](design/functional_decomposition.yaml#L51), [Generate Signing Key](design/functional_decomposition.yaml#L49)                                                    |

### Repudiation

| Threat                                         | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------- | ------ | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent denies performing a privileged operation | Medium | Low        | Low    | All token operations and authorization decisions are written to agent-auth's audit log before the response is sent. Targets: **likelihood** (comprehensive logging). Implemented: [Log Token Operation](design/functional_decomposition.yaml#L89), [Log Authorization Decision](design/functional_decomposition.yaml#L91) |
| Audit log tampered post-hoc                    | High   | Low        | Medium | agent-auth's audit log is append-only in the current implementation. Targets: **likelihood** (append-only reduces accidental or casual tampering). Cryptographic chaining is tracked in [#103](https://github.com/aidanns/agent-auth/issues/103).                                                                         |

### Information disclosure

| Threat                                  | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------- | ------ | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Token scopes exposed via database read  | Medium | Low        | Low    | Scope fields are AES-256-GCM encrypted at rest; plaintext is only available in-process after decryption. Targets: **impact** (data unreadable without key). Implemented: [Encrypt Field](design/functional_decomposition.yaml#L69), [Query Tokens](design/functional_decomposition.yaml#L67)                                    |
| HMAC signing key extracted from keyring | High   | Low        | Medium | The key is held in the OS keyring (Keychain on macOS, libsecret on Linux). No in-memory caching beyond the process lifetime. Targets: **likelihood** (OS keyring restricts access). Implemented: [Load Signing Key](design/functional_decomposition.yaml#L51), [Generate Signing Key](design/functional_decomposition.yaml#L49) |
| Token value logged in plaintext         | High   | Low        | Low    | Tokens are never written to logs. Audit records reference token family IDs only. Targets: **likelihood**. Implemented: [Log Token Operation](design/functional_decomposition.yaml#L89), [Log Authorization Decision](design/functional_decomposition.yaml#L91)                                                                  |

### Denial of service

| Threat                                       | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                              |
| -------------------------------------------- | ------ | ---------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Oversized request body exhausting agent-auth | Low    | Medium     | Low    | Request bodies are capped at 1 MiB. Targets: **likelihood** (attacker cannot send arbitrarily large payloads). Implemented: [Serve Validate Endpoint](design/functional_decomposition.yaml#L76)                                         |
| Rapid token-creation filling `tokens.db`     | Low    | Low        | Low    | No rate limiting currently; the server is local-only so the attack requires code execution on the host. Targets: **neither** (not yet mitigated). Rate limiting is tracked in [#102](https://github.com/aidanns/agent-auth/issues/102). |

### Elevation of privilege

Scope tiers define what approval a request requires: `allow` = immediately
permitted if the token holds the scope; `prompt` = the operation is held pending
real-time human approval via the JIT notification flow even if the token holds
the scope. An AI agent cannot self-approve a `prompt`-tier request regardless of
what scopes its token carries; a human must respond to the notification to
unblock the operation.

| Threat                                                                 | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------- | ------ | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AI agent invokes a `prompt`-tier scope without triggering JIT approval | High   | Low        | Medium | Scope tier is resolved server-side on every validation call; the agent cannot bypass the approval flow by presenting a token that holds the scope. Targets: **likelihood**. Implemented: [Check Scope Authorization](design/functional_decomposition.yaml#L28), [Resolve Access Tier](design/functional_decomposition.yaml#L30), [Request Approval](design/functional_decomposition.yaml#L35)                                    |
| Malicious notification plugin runs in-process                          | High   | Low        | Medium | Plugin runs inside the agent-auth process that holds signing and encryption keys. Targets: **likelihood** (partial: user controls which plugin is installed). Current mitigation: only install plugins from trusted sources under your user account. Out-of-process migration tracked in [#6](https://github.com/aidanns/agent-auth/issues/6). Implemented: [Load Notification Plugin](design/functional_decomposition.yaml#L38) |
| things-bridge constructs arbitrary argv passed to things-client CLI    | Medium | Low        | Low    | things-bridge constructs the argv from validated, schema-matched request parameters, not from raw client input. Targets: **likelihood**. Implemented: [Delegate Token Validation](design/functional_decomposition.yaml#L111), [Fetch Things Data](design/functional_decomposition.yaml#L113)                                                                                                                                     |

## Key handling

- The HMAC signing key and AES-256-GCM encryption key are generated on first
  run and stored in the system keyring (macOS Keychain or libsecret/gnome-keyring
  on Linux).
- Keys are loaded into memory at server startup and never written to disk in
  plaintext.
- Keys are not rotated automatically. Manual rotation requires revoking all
  existing token families (as their HMAC signatures will no longer verify) and
  generating a new key.
- The keyring service name is `agent-auth`; the key name is `signing-key` (HMAC)
  and `encryption-key` (AES-256-GCM).

## Revocation flow

1. **Explicit revocation**: `agent-auth token revoke <family-id>` marks all
   tokens in the family as revoked in `tokens.db`. Subsequent validation calls
   return `401 Unauthorized`.
2. **Refresh-token reuse detection**: presenting a previously used refresh token
   triggers immediate family-wide revocation (all access and refresh tokens in
   the family are invalidated). This limits the blast radius of a stolen refresh
   token.
3. **Token expiry**: access tokens carry an expiry timestamp; validation rejects
   expired tokens with `401 Unauthorized`. things-cli retries with the refresh
   token on `token_expired` responses.
4. **Key rotation**: replacing the signing key in the keyring invalidates all
   previously issued tokens on the next validation call, acting as a
   revocation-of-last-resort.

## Audit surface

The following events are written to **agent-auth's** audit log (stderr +
structured log). Consolidating audit events across all services (agent-auth,
things-bridge) into a single structured JSON schema is tracked in
[#100](https://github.com/aidanns/agent-auth/issues/100).

- Token family created (family ID, scopes, tier, timestamp)
- Token validated (family ID, scope checked, outcome, timestamp)
- Token refreshed (old family ID, new family ID, timestamp)
- Token revoked (family ID, reason, timestamp)
- Token rotated (old family ID, new family ID, timestamp)
- JIT approval requested (family ID, scope, timestamp)
- JIT approval granted or denied (family ID, scope, outcome, timestamp)
- Scope modified (family ID, changed scopes, timestamp)

Token values (the `aa_` or `rt_` strings) are never logged. All records reference
family IDs only.

## Cybersecurity standard

This project adopts **NIST SP 800-53 Revision 5** as its reference cybersecurity
standard. The five control families below are in scope because each maps to a
specific component of the current implementation:

- **AC — Access Control**: the three-tier scope model (`allow`/`prompt`/`deny`)
  and the per-family scope set enforced in `src/agent_auth/scopes.py` and the
  [Check Scope Authorization](design/functional_decomposition.yaml#L28) and
  [Resolve Access Tier](design/functional_decomposition.yaml#L30) leaf
  functions.
- **AU — Audit and Accountability**: the append-only audit log in
  `src/agent_auth/audit.py`, fed by every token lifecycle event and
  authorization decision.
- **IA — Identification and Authentication**: HMAC-SHA256 signed tokens with
  per-family revocation (`src/agent_auth/tokens.py`) and the agent-auth
  server as the sole validation authority
  (`src/agent_auth/server.py` — the `/validate` endpoint).
- **SC — System and Communications Protection**: AES-256-GCM field encryption
  (`src/agent_auth/crypto.py`) and the signing/encryption keys held in the
  system keyring (`src/agent_auth/keys.py`). Transport protection is a known
  gap — see the SC-8 note below.
- **SI — System and Information Integrity**: request-body size caps and
  schema-validated parameters before subprocess argv construction
  (`src/things_bridge/server.py`).

Controls outside these families are out of scope for the current codebase; the
product is a local, single-user authorization system and does not cover
personnel, supply-chain, physical, or enterprise-scale controls. Applicability
assessments for new features are documented in ADRs under
`design/decisions/`.

### Control families relevant to this project

The table below lists selected controls with their current implementation status.
`Implemented` means the control is satisfied by a deployed function.
`Partial` means the control is partially satisfied with a known gap.
`Planned` means the control is selected but not yet implemented.

| Family                               | ID  | Selected controls                                                                                                                                                                                                                                                                             | Status                                                                                                                                                                                                            |
| ------------------------------------ | --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Access Control                       | AC  | AC-3 (Access Enforcement) — scope-based token validation; AC-6 (Least Privilege) — scopes are narrowly granted per token family                                                                                                                                                               | Implemented                                                                                                                                                                                                       |
| Audit and Accountability             | AU  | AU-2 (Event Logging) — token operations and authorization decisions logged; AU-3 (Content of Audit Records) — family ID, scope, outcome, timestamp per record; AU-9 (Protection of Audit Information) — append-only log; AU-12 (Audit Record Generation) — all token lifecycle events covered | Partial — AU-9 lacks cryptographic integrity ([#103](https://github.com/aidanns/agent-auth/issues/103)); AU-3 schema is not yet shared across services ([#100](https://github.com/aidanns/agent-auth/issues/100)) |
| Identification and Authentication    | IA  | IA-5 (Authenticator Management) — HMAC-signed tokens with expiry and family-wide revocation; IA-9 (Service Identification and Authentication) — agent-auth is the sole token authority; bridges re-validate on every request                                                                  | Implemented                                                                                                                                                                                                       |
| System and Communications Protection | SC  | SC-8 (Transmission Confidentiality and Integrity) — loopback-only deployment (host-to-host); SC-28 (Protection of Information at Rest) — AES-256-GCM encryption for sensitive DB columns                                                                                                      | Partial — SC-8 not satisfied for devcontainer-to-host traffic ([#101](https://github.com/aidanns/agent-auth/issues/101))                                                                                          |
| System and Information Integrity     | SI  | SI-10 (Information Input Validation) — request body size cap (1 MiB); schema-validated parameters before subprocess argv construction; SI-12 (Information Management and Retention) — token expiry enforced; consumed refresh tokens marked and not reused                                    | Implemented                                                                                                                                                                                                       |

Control applicability assessments for new features should be documented in
`design/decisions/` ADRs at the time the feature is implemented.

## Vulnerability reporting

This is a personal project. If you find a security issue, **do not open a
public GitHub issue.** Use
[GitHub private vulnerability reporting](https://github.com/aidanns/agent-auth/security/advisories/new)
to disclose the issue confidentially.
