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
- **Refresh token** — longer-lived (default 7 days). Used only to obtain a new access/refresh token pair from agent-auth. Single-use: consumed on use and replaced.

### Token Lifecycle

**Creation:**
```
agent-auth token create --scope things:read --scope outlook:mail:read --expires 7d
→ access_token: aa_xxx_yyy
  refresh_token: rt_xxx_yyy
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

**Rotation:**
```
agent-auth token rotate <token-id> --expires 7d
→ old token family revoked
← new access_token + refresh_token with same scopes
```

Manual rotation creates a completely new token family. Used when changing scopes or as a periodic security practice.

**Revocation:**
```
agent-auth token revoke <token-id>
→ entire token family revoked (all access + refresh tokens)
```

### CLI Credential Storage

The CLI stores its current credentials locally:

```
~/.config/things-cli/credentials.json
{
  "access_token": "aa_xxx_yyy",
  "refresh_token": "rt_xxx_yyy",
  "bridge_url": "http://host.docker.internal:9200",
  "auth_url": "http://host.docker.internal:9100"
}
```

On 401 from the bridge, the CLI automatically attempts a refresh before failing.

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

### JIT approval (prompt tier)

```
things-cli complete <id>
  → POST http://host:9200/complete
    Authorization: Bearer aa_xxx_yyy

  things-bridge:
    → POST http://localhost:9100/validate
      {"token": "aa_xxx_yyy", "required_scope": "things:write"}
    ← {"valid": true, "tier": "prompt"}
    → POST http://localhost:9100/approval/request
      {"token": "aa_xxx_yyy", "scope": "things:write", "description": "Complete todo: Buy milk"}
    ← blocks until user responds to macOS notification
    ← {"approved": true, "grant": "once"}
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
{"token": "aa_xxx_yyy", "required_scope": "things:read"}
```

Response (200):
```json
{"valid": true, "tier": "allowed"}
```

Response (401):
```json
{"valid": false, "error": "token_expired"}
```

Response (403):
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

Response (401 — token consumed, family revoked):
```json
{"error": "refresh_token_reuse_detected", "detail": "Token family revoked"}
```

### POST /approval/request

Request JIT approval for a prompt-tier scope. Blocks until the user responds.

Request:
```json
{
  "token": "aa_xxx_yyy",
  "scope": "things:write",
  "description": "Complete todo: Buy milk"
}
```

Response (200):
```json
{"approved": true, "grant": "session"}
```

Response (403):
```json
{"approved": false}
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
