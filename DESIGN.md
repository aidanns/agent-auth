# agent-auth Design

## Overview

agent-auth is a local authorization system for gating AI agent access to macOS applications via AppleScript. It provides scoped, short-lived tokens with JIT human approval for sensitive operations.

## Components

```
┌─────────────────────┐            ┌──────────────────────────────┐
│  Devcontainer        │            │  Host machine                 │
│                      │            │                               │
│  things-cli ───HTTP──────────▶  things-bridge ──AppleScript──▶ Things3
│                 │    │            │    │                           │
│                 │    │            │    │ HTTP (validate, approve)  │
│                 │    │            │    ▼                           │
│                 └─HTTP──────────▶  agent-auth                     │
│                      │            │    ├─ tokens.db                │
│                      │            │    └─ signing.key              │
└─────────────────────┘            └──────────────────────────────┘
```

### agent-auth

HTTP server running on the host. Sole owner of the token store and signing key.

Responsibilities:
- Token lifecycle: create, validate, refresh, revoke, rotate
- JIT approval: hold requests pending human approval via macOS notifications
- Scope policy: define which scopes exist and their access tier (allowed/prompt/denied)

### things-bridge (and future app bridges)

HTTP server running on the host. Receives requests from the CLI client, delegates token validation and approval to agent-auth, then executes AppleScript against the target application.

Responsibilities:
- Map HTTP endpoints to AppleScript operations
- Call agent-auth to validate tokens and request approval before executing
- Return structured results to the CLI client

Each macOS application gets its own bridge server. Bridges are independent of each other and only depend on agent-auth for authorization.

### things-cli (and future app CLIs)

Thin CLI client that can run anywhere (host or devcontainer). Sends HTTP requests to the corresponding bridge with a bearer token. Handles automatic token refresh on 401 responses.

Responsibilities:
- Provide a CLI interface for the application
- Pass the bearer token from local credential storage
- Automatically refresh expired access tokens using the refresh token
- Store credentials locally

## Authentication

### Token Format

Tokens are HMAC-signed strings:

```
aa_<token-id>_<hmac-signature>    # access token
rt_<token-id>_<hmac-signature>    # refresh token
```

The signature is computed over the token ID using a signing key stored at `~/.config/agent-auth/signing.key`. This prevents token forgery without access to the signing key.

### Token Pair

Each credential set consists of two tokens:

- **Access token** — short-lived (default 15 minutes). Sent with every request to app bridges via the `Authorization: Bearer` header.
- **Refresh token** — longer-lived (default 8 hours). Used only to obtain a new access/refresh token pair from agent-auth. Single-use: consumed on use and replaced.

### Token Lifecycle

**Creation:**
```
agent-auth token create --scope things:read --scope outlook:mail:read
→ access_token: aa_xxx_yyy
  refresh_token: rt_xxx_yyy
  family_id: fff
  expires_in: 900
```

Both tokens are displayed once. The user configures the CLI client with these credentials.

**Refresh:**
```
POST /token/refresh
{"refresh_token": "rt_xxx_yyy"}
→ old refresh token revoked
← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
```

The refresh token is single-use. If agent-auth receives a refresh request for an already-consumed token, it revokes the entire token family (all access and refresh tokens descended from the same original creation). This detects stolen refresh tokens: if the attacker and the legitimate client both try to refresh, one will hit a consumed token and trigger revocation.

**Scope modification:**
```
agent-auth token modify <family-id> --add-scope outlook:mail:read --remove-scope things:write
agent-auth token modify <family-id> --set-tier things:write=prompt
```

Updates the scopes on an existing token family. Takes effect immediately on the next `/validate` call — no new tokens are issued, and no client reconfiguration is needed. The client keeps using the same access and refresh tokens.

**Rotation:**
```
agent-auth token rotate <token-id>
→ old token family revoked
← new access_token + refresh_token with same scopes
```

Manual rotation creates a completely new token family. Used as a periodic security practice or when a full credential reset is needed.

**Revocation:**
```
agent-auth token revoke <token-id>
→ entire token family revoked (all access + refresh tokens)
```

**Re-issuance (expired refresh token):**

When a CLI attempts to refresh and receives a `refresh_token_expired` error, it can request re-issuance of a new token pair for the same token family. This requires JIT approval from the user on the host.

```
POST /token/reissue
{"family_id": "fff"}
← blocks — agent-auth triggers JIT approval interaction on the host
← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
```

Re-issuance inherits the scopes and tiers from the existing token family. It does not allow scope escalation. The old token family remains intact (it is not revoked) — re-issuance simply creates a new access/refresh token pair within the same family.

Re-issuance is only available for token families that are not revoked and whose refresh token has expired (not been consumed by reuse detection). If the family was revoked due to refresh token reuse, re-issuance is denied — the user must create a new token via the CLI.

The JIT approval interaction is deliberately unspecified: it could be a macOS notification, Touch ID, a YubiKey tap, or any other local authentication mechanism. The requirement is that the user must be physically present at the host and must explicitly approve the re-issuance.

### CLI Credential Storage

The CLI uses the system keyring to store credentials (access token, refresh token, family ID, endpoint URLs). The backend is selected automatically:

1. **macOS Keychain** — used on macOS hosts. Credentials are stored via the Keychain Services API.
2. **libsecret / gnome-keyring** — used in Linux environments (including devcontainers) where a Secret Service D-Bus backend is available.
3. **Plaintext file** — `~/.config/<app>-cli/credentials.json` with `0600` permissions. Only used when the `--credential-store=file` flag is explicitly passed. The CLI refuses to store credentials on disk without this flag.

All three backends are abstracted behind the Python `keyring` library. The CLI detects available backends at startup and uses the highest-priority one. If no keyring backend is available and `--credential-store=file` was not passed, the CLI exits with an error explaining the options.

Stored credentials:

| Key | Value |
|---|---|
| `access_token` | `aa_xxx_yyy` |
| `refresh_token` | `rt_xxx_yyy` |
| `family_id` | `fff` |
| `bridge_url` | `http://host.docker.internal:9200` |
| `auth_url` | `http://host.docker.internal:9100` |

On 401 from the bridge, the CLI automatically attempts a refresh. If the refresh token has expired, the CLI attempts re-issuance (which blocks on JIT approval). If re-issuance is denied or the family is revoked, the CLI fails and the user must create a new token.

## Authorization

### Permission Scopes

Scopes follow the pattern `<app>:<resource>` or `<app>:<resource>:<action>`:

```
things:read
things:write
outlook:mail:read
outlook:mail:send
outlook:calendar:read
outlook:calendar:write
outlook:contacts:read
outlook:contacts:write
```

Each token is issued with a fixed set of scopes. Scopes cannot be escalated via refresh — a refreshed token carries the same scopes as its predecessor.

### Access Tiers

Each scope on a token has one of three tiers:

- **allowed** — request executes immediately
- **prompt** — request is held until the user approves via macOS notification
- **denied** — request is rejected, tool is not available

Tiers are configured per-token at creation time:

```
agent-auth token create \
  --scope things:read=allowed \
  --scope things:write=prompt \
  --scope outlook:mail:send=denied \
  --expires 7d
```

If no tier is specified, the default is `allowed`.

### JIT Approval Flow

When a bridge calls agent-auth to validate a token for a `prompt`-tier scope:

1. agent-auth sends a macOS notification: "Claude wants to complete todo: Buy milk — Allow / Deny"
2. The validation request blocks until the user responds
3. On approval, agent-auth returns success and the bridge proceeds
4. On denial, agent-auth returns forbidden and the bridge rejects the request

Approval grants can be scoped:
- **Once** — this specific invocation only
- **Session** — allow this scope for the lifetime of the current access token
- **Time-boxed** — allow for the next N minutes

Session-level grants are stored in memory on the agent-auth server. They do not modify the token and expire when the access token expires or the server restarts.

## Request Flow

### Standard request (allowed tier)

```
things-cli inbox
  → GET http://host:9200/inbox
    Authorization: Bearer aa_xxx_yyy

  things-bridge:
    → POST http://localhost:9100/validate
      {"token": "aa_xxx_yyy", "required_scope": "things:read"}
    ← {"valid": true, "tier": "allowed"}
    → executes AppleScript
  ← 200 response with results
```

### Expired token with automatic refresh

```
things-cli inbox
  → GET http://host:9200/inbox
    Authorization: Bearer aa_xxx_yyy
  ← 401 Unauthorized

  things-cli:
    → POST http://host:9100/token/refresh
      {"refresh_token": "rt_xxx_yyy"}
    ← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
    → saves new credentials to disk

    → GET http://host:9200/inbox
      Authorization: Bearer aa_zzz_www
    ← 200 response with results
```

### Expired refresh token with JIT re-issuance

```
things-cli inbox
  → GET http://host:9200/inbox
    Authorization: Bearer aa_xxx_yyy
  ← 401 Unauthorized

  things-cli:
    → POST http://host:9100/token/refresh
      {"refresh_token": "rt_xxx_yyy"}
    ← 401 {"error": "refresh_token_expired"}

    → POST http://host:9100/token/reissue
      {"family_id": "fff"}
    ← blocks — agent-auth triggers JIT approval on the host
    ← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
    → saves new credentials to disk

    → GET http://host:9200/inbox
      Authorization: Bearer aa_zzz_www
    ← 200 response with results
```

### JIT approval (prompt tier)

```
things-cli complete <id>
  → POST http://host:9200/complete
    Authorization: Bearer aa_xxx_yyy

  things-bridge:
    → POST http://localhost:9100/validate
      {"token": "aa_xxx_yyy", "required_scope": "things:write", "description": "Complete todo: Buy milk"}
    ← blocks — agent-auth triggers macOS notification and waits for user response
    ← {"valid": true}
    → executes AppleScript
  ← 200 response with results
```

## Token Store

SQLite database at `~/.config/agent-auth/tokens.db`.

### Tables

**token_families:**
| Column | Type | Description |
|---|---|---|
| id | TEXT PK | Family ID |
| scopes | TEXT | JSON object mapping scope name to tier |
| created_at | TEXT | ISO 8601 timestamp |
| revoked | INTEGER | 0 or 1 |

**tokens:**
| Column | Type | Description |
|---|---|---|
| id | TEXT PK | Token ID |
| family_id | TEXT FK | References token_families.id |
| type | TEXT | "access" or "refresh" |
| expires_at | TEXT | ISO 8601 timestamp |
| consumed | INTEGER | 0 or 1 (for refresh tokens) |

**approval_grants:**
| Column | Type | Description |
|---|---|---|
| id | TEXT PK | Grant ID |
| token_id | TEXT | Access token this grant applies to |
| scope | TEXT | Scope that was approved |
| grant_type | TEXT | "once", "session", or "timed" |
| expires_at | TEXT | NULL for "once" and "session", ISO 8601 for "timed" |

## agent-auth HTTP API

### POST /validate

Validate a token and check scope authorization.

Request:
```json
{"token": "aa_xxx_yyy", "required_scope": "things:read", "description": "List inbox todos"}
```

The `description` field is optional. It is used in JIT approval notifications for prompt-tier scopes so the user can see what operation is being requested.

For `allowed`-tier scopes, the response is immediate:
```json
{"valid": true}
```

For `prompt`-tier scopes, the request blocks while agent-auth shows a macOS notification and waits for the user to approve or deny. The caller (bridge) sees the same response shape — it does not need to know whether approval was involved:
```json
{"valid": true}
```

Response (401 — invalid or expired token):
```json
{"valid": false, "error": "token_expired"}
```

Response (403 — scope denied or JIT approval denied):
```json
{"valid": false, "error": "scope_denied"}
```

### POST /token/refresh

Exchange a refresh token for a new access/refresh token pair.

Request:
```json
{"refresh_token": "rt_xxx_yyy"}
```

Response (200):
```json
{
  "access_token": "aa_zzz_www",
  "refresh_token": "rt_zzz_www",
  "expires_in": 900,
  "scopes": {"things:read": "allowed", "things:write": "prompt"}
}
```

Response (401 — token expired):
```json
{"error": "refresh_token_expired"}
```

Response (401 — token consumed, family revoked):
```json
{"error": "refresh_token_reuse_detected", "detail": "Token family revoked"}
```

### POST /token/reissue

Request a new access/refresh token pair for a token family whose refresh token has expired. Requires JIT approval from the user on the host.

Request:
```json
{"family_id": "fff"}
```

The request blocks while agent-auth triggers a JIT approval interaction on the host. The approval mechanism is implementation-defined (macOS notification, Touch ID, YubiKey, etc.).

Response (200 — approved):
```json
{
  "access_token": "aa_zzz_www",
  "refresh_token": "rt_zzz_www",
  "expires_in": 900,
  "scopes": {"things:read": "allowed", "things:write": "prompt"}
}
```

Response (403 — user denied re-issuance):
```json
{"error": "reissue_denied"}
```

Response (401 — family revoked or not found):
```json
{"error": "family_revoked"}
```

### GET /token/status

Introspect a token (read-only, for debugging).

Request:
```
Authorization: Bearer aa_xxx_yyy
```

Response (200):
```json
{
  "token_id": "xxx",
  "family_id": "fff",
  "type": "access",
  "scopes": {"things:read": "allowed", "things:write": "prompt"},
  "expires_at": "2026-04-12T12:15:00Z",
  "expires_in": 732
}
```

## Network Configuration

### Local (host only)

- agent-auth listens on `127.0.0.1:9100`
- things-bridge listens on `127.0.0.1:9200`
- CLIs call localhost directly

### Devcontainer

- agent-auth listens on `127.0.0.1:9100` (host only — bridges access via localhost)
- things-bridge listens on `0.0.0.0:9200` (accessible from devcontainer)
- CLIs use `host.docker.internal:9200` for bridge, `host.docker.internal:9100` for token refresh
- Docker port forwarding exposes 9200 and 9100 to the devcontainer

## Security Considerations

- The signing key never leaves the host. Only agent-auth reads it.
- The token store (SQLite) is only accessed by agent-auth.
- Bridges never see the signing key or token store — they delegate all auth decisions to agent-auth.
- CLIs are untrusted. They cannot escalate scopes. A stolen access token is useful for at most 15 minutes. A stolen refresh token is detected on reuse and triggers family revocation.
- agent-auth and bridge servers bind to localhost by default. Only bridge servers need to bind to 0.0.0.0 for devcontainer access.
- JIT approval notifications include a human-readable description of the operation so the user can make an informed decision.
