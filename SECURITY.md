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

## Threat model

The following STRIDE analysis covers the agent-auth server, things-bridge, and
things-cli. Threats are rated High / Medium / Low by impact × likelihood.

### Spoofing

| Threat | Rating | Mitigation |
|--------|--------|------------|
| Forged token presented to agent-auth `/validate` | High | HMAC-SHA256 signature over `prefix + token-id` prevents forgery without the signing key. |
| Cross-type token substitution (access token used as refresh token) | Medium | The token prefix (`aa_` vs `rt_`) is included in the HMAC input; a valid access-token signature does not verify for the refresh-token type. |
| Rogue process binding to 127.0.0.1:9100 before agent-auth | Medium | Mitigated by user being the sole operator of the host machine. No cryptographic protection against a co-located rogue process winning the bind race. |

### Tampering

| Threat | Rating | Mitigation |
|--------|--------|------------|
| Direct modification of `tokens.db` | High | Scope and HMAC-signature fields are AES-256-GCM encrypted at rest; modification without the key produces authentication-tag failures on read. |
| Replay of a revoked token | High | Revocation writes `revoked_at` to the token record; validation checks `revoked_at IS NULL` before accepting. Reuse of a refresh token triggers family-wide revocation. |
| Tampering with the signing key in the system keyring | High | Requires OS-level access to the keyring (macOS Keychain or libsecret). If the key is replaced, all previously issued tokens become invalid on next validation. |

### Repudiation

| Threat | Rating | Mitigation |
|--------|--------|------------|
| Agent denies performing a privileged operation | Medium | All token operations and authorization decisions are written to the audit log before the response is sent. |
| Audit log tampered post-hoc | Low | Audit log is append-only in the current implementation; cryptographic chaining is a future hardening step. |

### Information disclosure

| Threat | Rating | Mitigation |
|--------|--------|------------|
| Token scopes exposed via database read | Medium | Scope fields are AES-256-GCM encrypted at rest; plaintext is only available in-process after decryption. |
| HMAC signing key extracted from keyring | High | The key is held in the OS keyring (Keychain on macOS, libsecret on Linux). No in-memory caching beyond the process lifetime. |
| Token value logged in plaintext | Low | Tokens are never written to logs. Audit records reference token family IDs only. |

### Denial of service

| Threat | Rating | Mitigation |
|--------|--------|------------|
| Oversized request body exhausting agent-auth | Medium | Request bodies are capped at 1 MiB. |
| Rapid token-creation filling `tokens.db` | Low | No rate limiting currently; the server is local-only so the attack requires code execution on the host. Rate limiting is a future hardening step. |

### Elevation of privilege

| Threat | Rating | Mitigation |
|--------|--------|------------|
| AI agent escalates from `allow`-tier to `prompt`-tier scope without JIT approval | High | Scope tier is validated server-side on every request; the agent cannot self-approve `prompt`-tier requests. |
| Malicious notification plugin runs in-process | High | Tracked in [#6](https://github.com/aidanns/agent-auth/issues/6). Current mitigation: only install plugins from trusted sources under your user account. |
| things-cli constructs arbitrary argv passed to things-client CLI | Medium | things-bridge constructs the argv from validated, schema-matched request parameters, not from raw client input. |

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

The following events are written to the audit log (stderr + structured log):

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
standard. NIST SP 800-53 Rev 5 is a widely-used, publicly-available catalog of
security and privacy controls applicable to information systems, independent of
sector or organization type. It maps naturally onto a token-based authorization
system that handles key material and sensitive user data.

**Rationale**: The project handles cryptographic key material (HMAC signing key,
AES-256-GCM encryption key), a local SQLite token store, and a JIT approval
surface. NIST SP 800-53 Rev 5 provides clear control families for these
responsibilities (AC, AU, IA, SC, SI) with well-defined implementation guidance,
and its control catalog is machine-readable for automated compliance checking.

### Control families relevant to this project

| Family | ID | Selected controls |
|--------|----|-------------------|
| Access Control | AC | AC-2 (Account Management), AC-3 (Access Enforcement), AC-6 (Least Privilege), AC-17 (Remote Access) |
| Audit and Accountability | AU | AU-2 (Event Logging), AU-3 (Content of Audit Records), AU-9 (Protection of Audit Information), AU-12 (Audit Record Generation) |
| Identification and Authentication | IA | IA-5 (Authenticator Management), IA-9 (Service Identification and Authentication) |
| System and Communications Protection | SC | SC-8 (Transmission Confidentiality and Integrity), SC-28 (Protection of Information at Rest) |
| System and Information Integrity | SI | SI-10 (Information Input Validation), SI-12 (Information Management and Retention) |

Implementation plans for new features should verify compliance against the
controls above that are in scope for the change. Control applicability
assessments live in `design/decisions/` ADRs.

## Vulnerability reporting

This is a personal project with no published releases or user base beyond the
author. If you find a security issue:

1. **Do not open a public GitHub issue.** Use
   [GitHub private vulnerability reporting](https://github.com/aidanns/agent-auth/security/advisories/new)
   to disclose the issue confidentially.
2. Alternatively, email **aidanns@gmail.com** with the subject line
   `[agent-auth] Security vulnerability`.
3. Expect acknowledgment within 7 days and a fix or mitigation within 30 days.

There is no bug bounty program.
