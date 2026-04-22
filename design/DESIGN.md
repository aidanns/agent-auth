<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# agent-auth Design

## Overview

agent-auth is a local authorization system for gating AI agent access to host applications. It provides scoped, short-lived tokens with JIT human approval for sensitive operations.

## Components

```
┌──────────────────────┐            ┌─────────────────────────────────────────────┐
│  Devcontainer        │            │  Host machine                               │
│                      │            │                                             │
│  app-cli ─────────HTTP───────────▶  app-bridge ──────────────▶ External System  │
│                 │    │            │    │                                        │
│                 │    │            │    │ HTTP (validate, approve)               │
│                 │    │            │    ▼                                        │
│                 └─HTTP───────────▶  agent-auth                                  │
│                      │            │    ├─ tokens.db                             │
│                      │            │    └─ signing key (keyring)                 │
└──────────────────────┘            └─────────────────────────────────────────────┘
```

### agent-auth

HTTP server running on the host. Sole owner of the token store and signing key.

Responsibilities:

- Token lifecycle: create, validate, refresh, revoke, rotate
- Scope modification: add, remove, or change tiers on existing token families
- JIT approval: hold requests pending human approval via a configurable notification plugin
- Scope policy: define which scopes exist and their access tier (allow/prompt/deny)
- Audit logging: record all token operations and authorization decisions

### things-bridge (and future app bridges)

HTTP server running on the host. Receives requests from the CLI client, delegates token validation and approval to agent-auth, then interacts with the target external system.

Responsibilities:

- Map HTTP endpoints to external system interactions
- Call agent-auth to validate tokens and request approval before executing
- Return structured results to the CLI client

Each external system gets its own bridge server. Bridges are independent of each other and only depend on agent-auth for authorization.

The first concrete bridge is `things-bridge`. It listens on `127.0.0.1:9200` by default and currently exposes read-only endpoints; write and JIT-gated endpoints are a follow-up. The bridge itself contains no Things 3 logic — it shells out to a separately-packaged Things-client CLI (see below) for every read request, treating it as a black box that answers an argv with JSON on stdout.

The Things-client surface (`list_todos`, `get_todo`, `list_projects`, `get_project`, `list_areas`, `get_area`) is exposed as the `ThingsClient` Protocol in `things_models.client`. The bridge's only in-process implementation is `ThingsSubprocessClient`, which translates each protocol call into an argv, runs the configured client CLI as a subprocess, and rehydrates the resulting JSON into `Todo` / `Project` / `Area` dataclasses. The command to run is controlled by `Config.things_client_command` (default `["things-client-cli-applescript"]`). Two concrete client CLIs exist today:

- **`things-client-cli-applescript`** — production client, ships with the dist. Runs on macOS, talks to Things 3 via `osascript`. No authentication (the trust boundary is that the user ran it locally).
- **`things-client-cli-fake`** — test-only, never shipped. Reads an in-memory store from a YAML fixture file and lives under `tests/things_client_fake/`. Invoked as `python -m tests.things_client_fake --fixtures PATH`. Lets the agent-auth + things-bridge + things-cli stack run end-to-end on Linux without `osascript` or Things 3.

The subprocess contract is stable and publicly documented so the bridge can adopt alternative clients (a future persistent AppleScript host, a non-macOS Things client) without code changes. See `design/decisions/0003-things-client-cli-split.md` for the rationale; `design/decisions/0001-things-client-fake.md` for the client-level-fake history it supersedes.

Read-only endpoints. Read endpoints require the `things:read` scope; the health endpoint requires `things-bridge:health` (mirroring the agent-auth health pattern — see `GET /agent-auth/health` below).

| Method | Path                                                        | Scope                  | Description                                   |
| ------ | ----------------------------------------------------------- | ---------------------- | --------------------------------------------- |
| GET    | `/things-bridge/v1/todos?list=&project=&area=&tag=&status=` | `things:read`          | List todos, optionally filtered               |
| GET    | `/things-bridge/v1/todos/{id}`                              | `things:read`          | Fetch one todo by Things id                   |
| GET    | `/things-bridge/v1/projects?area=`                          | `things:read`          | List projects, optionally filtered by area id |
| GET    | `/things-bridge/v1/projects/{id}`                           | `things:read`          | Fetch one project by Things id                |
| GET    | `/things-bridge/v1/areas`                                   | `things:read`          | List all areas                                |
| GET    | `/things-bridge/v1/areas/{id}`                              | `things:read`          | Fetch one area by Things id                   |
| GET    | `/things-bridge/health`                                     | `things-bridge:health` | Liveness / readiness probe                    |

Error responses from the bridge:

| Status | Body                                    | Cause                                                                             |
| ------ | --------------------------------------- | --------------------------------------------------------------------------------- |
| 401    | `{"error": "unauthorized"}`             | Missing, malformed, or invalid bearer token                                       |
| 401    | `{"error": "token_expired"}`            | agent-auth reported the access token has expired (CLI retries with refresh)       |
| 403    | `{"error": "scope_denied"}`             | Token does not carry `things:read`                                                |
| 404    | `{"error": "not_found"}`                | Unknown path or unknown Things id                                                 |
| 405    | `{"error": "method_not_allowed"}`       | Non-GET verb on a read-only endpoint (writes are a follow-up)                     |
| 502    | `{"error": "authz_unavailable"}`        | agent-auth is unreachable                                                         |
| 502    | `{"error": "things_unavailable"}`       | Client subprocess failed, timed out, exited non-zero, or emitted malformed output |
| 503    | `{"error": "things_permission_denied"}` | macOS Automation permission not granted for Things                                |

Error bodies intentionally omit server-side detail: the client subprocess's stderr can contain local filesystem paths, usernames, or script fragments, so the bridge returns only a canonical error code. Full error detail (including subprocess stderr) is forwarded verbatim to the bridge's own stderr for operator diagnostics.

### Things-client subprocess contract

Every read-path request to the bridge produces one subprocess invocation of the configured Things-client command. The contract is public and fixed:

- **argv** — `<command...> <resource> <verb> [flags]` (e.g. `things-client-cli-applescript todos list --status open`). The resource / verb / flag surface mirrors `things-cli`'s read commands.
- **stdout** — JSON, always. Success: `{"todos": [...]}`, `{"todo": {...}}`, `{"projects": [...]}`, `{"project": {...}}`, `{"areas": [...]}`, `{"area": {...}}`. Error: `{"error": "<code>", "detail": "<operator-only text>"}` where `<code>` is one of `not_found`, `things_permission_denied`, or `things_unavailable`.
- **exit code** — 0 on success, non-zero on error. The JSON body is authoritative for the error *kind*; the exit code only distinguishes success from failure. The bridge raises `ThingsError` if the stdout is missing, non-JSON, or not an object (protocol violation).
- **stderr** — operator diagnostics only. The bridge captures it and forwards it verbatim to its own stderr. HTTP response bodies never include stderr content.

See `src/things_client_common/cli.py` for the shared argparse / dispatcher that both client CLIs use to emit this contract, and `src/things_bridge/things_client.py` for the client-side implementation.

### things-cli (and future app CLIs)

Thin CLI client that can run anywhere (host or devcontainer). Sends HTTP requests to the corresponding bridge with a bearer token. Handles automatic token refresh on 401 responses.

Responsibilities:

- Provide a CLI interface for the application
- Pass the bearer token from local credential storage
- Automatically refresh expired access tokens using the refresh token; if the refresh token itself has expired, request re-issuance (which blocks on JIT approval)
- Store credentials in the system keyring (see CLI Credential Storage below)

`things-cli` ships the following read-only commands (paired with `login` / `logout` / `status` for credential management):

- `things-cli todos list [--list ID] [--project ID] [--area ID] [--tag NAME] [--status open|completed|canceled]`
- `things-cli todos show <id>`
- `things-cli projects list [--area ID]`
- `things-cli projects show <id>`
- `things-cli areas list`
- `things-cli areas show <id>`

All commands accept `--json` for machine-readable output.

## Authentication

### Token Format

Tokens are HMAC-signed strings:

```
aa_<token-id>_<hmac-signature>    # access token
rt_<token-id>_<hmac-signature>    # refresh token
```

The signature is computed over the token ID using a signing key stored in the system keyring (macOS Keychain or libsecret/gnome-keyring). agent-auth generates the key on first startup if it does not already exist in the keyring. This prevents token forgery without access to the signing key and avoids storing key material as a plaintext file on disk.

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
POST /agent-auth/v1/token/refresh
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
POST /agent-auth/v1/token/reissue
{"family_id": "fff"}
← blocks — agent-auth triggers JIT approval via configured notification plugin
← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
```

Re-issuance inherits the scopes and tiers from the existing token family. It does not allow scope escalation. The old token family remains intact (it is not revoked) — re-issuance simply creates a new access/refresh token pair within the same family.

Re-issuance is only available for token families that are not revoked and whose refresh token has expired (not been consumed by reuse detection). If the family was revoked due to refresh token reuse, re-issuance is denied — the user must create a new token via the CLI.

The JIT approval interaction uses the same configurable notification plugin as prompt-tier scope approval. The requirement is that the user must be physically present at the host and must explicitly approve the re-issuance.

### CLI Credential Storage

The CLI uses the system keyring to store credentials (access token, refresh token, family ID, endpoint URLs). The backend is selected automatically:

1. **macOS Keychain** — used on macOS hosts. Credentials are stored via the Keychain Services API.
2. **libsecret / gnome-keyring** — used in Linux environments (including devcontainers) where a Secret Service D-Bus backend is available.
3. **Plaintext file** — `~/.config/<app>-cli/credentials.yaml` with `0600` permissions. Only used when the `--credential-store=file` flag is explicitly passed. The CLI refuses to store credentials on disk without this flag.

All three backends are abstracted behind the Python `keyring` library. The CLI detects available backends at startup and uses the highest-priority one. If no keyring backend is available and `--credential-store=file` was not passed, the CLI exits with an error explaining the options.

Stored credentials:

| Key             | Value                              |
| --------------- | ---------------------------------- |
| `access_token`  | `aa_xxx_yyy`                       |
| `refresh_token` | `rt_xxx_yyy`                       |
| `family_id`     | `fff`                              |
| `bridge_url`    | `http://host.docker.internal:9200` |
| `auth_url`      | `http://host.docker.internal:9100` |

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

- **allow** — request executes immediately
- **prompt** — request is held until the user approves via a configured notification plugin
- **deny** — request is rejected, tool is not available

Tiers are configured per-token at creation time and can be adjusted later via `agent-auth token modify`:

```
agent-auth token create \
  --scope things:read=allow \
  --scope things:write=prompt \
  --scope outlook:mail:send=deny
```

If no tier is specified, the default is `allow`.

### JIT Approval Flow

When a bridge calls agent-auth to validate a token for a `prompt`-tier scope:

1. agent-auth requests user approval via the configured notification plugin (desktop notification by default if no other method is configured)
2. The validation request blocks until the user responds
3. On approval, agent-auth returns success and the bridge proceeds
4. On denial, agent-auth returns forbidden and the bridge rejects the request

The notification plugin is configured in agent-auth's configuration file, following a similar model to Claude Code hooks. This allows different notification methods (desktop notifications, Touch ID, YubiKey, custom scripts, etc.) to be swapped in without changing agent-auth itself.

Approval grants can be scoped:

- **Once** — this specific invocation only
- **Time-boxed** — allow for the next N minutes

Time-boxed grants are held in memory on the agent-auth server. They do not modify the token and expire after their duration elapses or when the server restarts, whichever comes first. Notification plugins can surface "for this session" as a UX-level shortcut for a 60-minute time-boxed grant.

## Request Flow

### Standard request (allow tier)

```
app-cli inbox
  → GET http://host:9200/app-bridge/inbox
    Authorization: Bearer aa_xxx_yyy

  app-bridge:
    → POST http://localhost:9100/agent-auth/v1/validate
      {"token": "aa_xxx_yyy", "required_scope": "app:read"}
    ← {"valid": true, "tier": "allow"}
    → interacts with external system
  ← 200 response with results
```

### Expired token with automatic refresh

```
app-cli inbox
  → GET http://host:9200/app-bridge/inbox
    Authorization: Bearer aa_xxx_yyy
  ← 401 Unauthorized

  app-cli:
    → POST http://host:9100/agent-auth/v1/token/refresh
      {"refresh_token": "rt_xxx_yyy"}
    ← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
    → saves new credentials

    → GET http://host:9200/app-bridge/inbox
      Authorization: Bearer aa_zzz_www
    ← 200 response with results
```

### Expired refresh token with JIT re-issuance

```
app-cli inbox
  → GET http://host:9200/app-bridge/inbox
    Authorization: Bearer aa_xxx_yyy
  ← 401 Unauthorized

  app-cli:
    → POST http://host:9100/agent-auth/v1/token/refresh
      {"refresh_token": "rt_xxx_yyy"}
    ← 401 {"error": "refresh_token_expired"}

    → POST http://host:9100/agent-auth/v1/token/reissue
      {"family_id": "fff"}
    ← blocks — agent-auth triggers JIT approval on the host
    ← {"access_token": "aa_zzz_www", "refresh_token": "rt_zzz_www", "expires_in": 900}
    → saves new credentials

    → GET http://host:9200/app-bridge/inbox
      Authorization: Bearer aa_zzz_www
    ← 200 response with results
```

### JIT approval (prompt tier)

```
app-cli complete <id>
  → POST http://host:9200/app-bridge/complete
    Authorization: Bearer aa_xxx_yyy

  app-bridge:
    → POST http://localhost:9100/agent-auth/v1/validate
      {"token": "aa_xxx_yyy", "required_scope": "app:write", "description": "Complete todo: Buy milk"}
    ← blocks — agent-auth triggers notification via configured plugin and waits for user response
    ← {"valid": true}
    → interacts with external system
  ← 200 response with results
```

## Token Store

SQLite database at `~/.config/agent-auth/tokens.db`.

### Encryption

Sensitive column values are encrypted at the field level using AES-256-GCM before being written to the database. The encryption key is stored in the system keyring (macOS Keychain or libsecret/gnome-keyring). agent-auth generates this key on first startup if it does not already exist.

Non-sensitive columns (IDs, timestamps, flags, types) are stored in plaintext so they remain queryable and indexable. Sensitive columns (token HMAC signatures, scope definitions, approval scopes) are encrypted. An attacker with the database file but not the keyring can see that tokens exist and when they expire, but cannot forge or use them.

Encrypted columns are marked with (E) in the table definitions below.

### Tables

**token_families:**

| Column     | Type     | Description                            |
| ---------- | -------- | -------------------------------------- |
| id         | TEXT PK  | Family ID                              |
| scopes     | BLOB (E) | JSON object mapping scope name to tier |
| created_at | TEXT     | ISO 8601 timestamp                     |
| revoked    | INTEGER  | 0 or 1                                 |

**tokens:**

| Column         | Type     | Description                                          |
| -------------- | -------- | ---------------------------------------------------- |
| id             | TEXT PK  | Token ID (family ID portion only, no HMAC signature) |
| hmac_signature | BLOB (E) | HMAC signature portion of the token                  |
| family_id      | TEXT FK  | References token_families.id                         |
| type           | TEXT     | "access" or "refresh"                                |
| expires_at     | TEXT     | ISO 8601 timestamp                                   |
| consumed       | INTEGER  | 0 or 1 (for refresh tokens)                          |

Approval grants are held in memory on the agent-auth server (see the approval flow above) and have no persistent table.

## API Versioning Policy

All HTTP endpoints (both agent-auth and things-bridge) are versioned under a
`/v1/` path segment. This allows breaking changes to be introduced under `/v2/`
while existing clients continue to use `/v1/`.

Health and metrics endpoints (`/agent-auth/health`, `/things-bridge/health`,
and the future `/agent-auth/metrics` / `/things-bridge/metrics` — tracked in
#26) are unversioned by convention — probes, monitoring tools, and Prometheus
scrapes should always be able to reach them regardless of API version.

**What constitutes a breaking change (requires `/v2/`):**

- Removing a field from a response body
- Renaming a field or error code
- Changing the meaning of a status code or field value
- Removing an endpoint

**Non-breaking changes (stay on current version):**

- Adding new optional request fields
- Adding new response fields (clients must ignore unknown fields)
- Adding new endpoints
- Adding new error codes

**Deprecation window:** When a breaking change is required, the old version
remains supported for 30 days before removal. The deprecation is announced
via changelog and a `Sunset` response header.

Error codes and audit-log event schemas are also part of the public API
surface; see `design/error-codes.md` for the full error taxonomy.

## agent-auth HTTP API

All endpoints are prefixed with `/agent-auth/v1/` to allow hosting behind a
shared reverse proxy alongside bridge servers. The health endpoint is unversioned
(see versioning policy above).

### POST /agent-auth/v1/validate

Validate a token and check scope authorization.

Request:

```json
{"token": "aa_xxx_yyy", "required_scope": "things:read", "description": "List inbox todos"}
```

The `description` field is optional. It is passed to the notification plugin for prompt-tier scopes so the user can see what operation is being requested.

For `allow`-tier scopes, the response is immediate:

```json
{"valid": true}
```

For `prompt`-tier scopes, the request blocks while agent-auth triggers the configured notification plugin and waits for the user to approve or deny. The caller (bridge) sees the same response shape — it does not need to know whether approval was involved:

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

### POST /agent-auth/v1/token/refresh

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
  "scopes": {"things:read": "allow", "things:write": "prompt"}
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

### POST /agent-auth/v1/token/reissue

Request a new access/refresh token pair for a token family whose refresh token has expired. Requires JIT approval from the user on the host.

Request:

```json
{"family_id": "fff"}
```

The request blocks while agent-auth triggers JIT approval via the configured notification plugin.

Response (200 — approved):

```json
{
  "access_token": "aa_zzz_www",
  "refresh_token": "rt_zzz_www",
  "expires_in": 900,
  "scopes": {"things:read": "allow", "things:write": "prompt"}
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

### GET /agent-auth/health

Liveness / readiness probe. Requires an access token carrying the
`agent-auth:health` scope (tier `allow` or `prompt`). Returns 200 when
the token store is reachable, 503 when `store.ping()` fails.

Request:

```
Authorization: Bearer aa_xxx_yyy
```

Response (200):

```json
{"status": "ok"}
```

Response (401 — no / invalid / expired token):

```json
{"error": "missing_token"}
```

Response (403 — token lacks the `agent-auth:health` scope):

```json
{"error": "scope_denied"}
```

Response (503 — store unreachable):

```json
{"status": "unhealthy"}
```

Callers (integration-test harness, production probes) must provision a
token with the `agent-auth:health` scope and present it on every call.
The integration-test fixture polls for *any* HTTP response (including
401\) as its container-readiness signal, then issues a properly-scoped
token for the actual health assertion.

### GET /agent-auth/v1/token/status

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
  "scopes": {"things:read": "allow", "things:write": "prompt"},
  "expires_at": "2026-04-12T12:15:00Z",
  "expires_in": 732
}
```

### Management endpoint authentication

All five management endpoints require `Authorization: Bearer <access_token>`
where the access token's family has `agent-auth:manage=allow` in its scopes.
On first startup, the server creates this management token family automatically
and stores the refresh token in the OS keyring. Retrieve the refresh token via
`agent-auth management-token show`, then exchange it for an access token via
`POST /agent-auth/v1/token/refresh` before calling management endpoints. See
[ADR 0014](decisions/0014-management-endpoint-auth.md) for the rationale.

Errors returned when auth is missing or invalid: `401 missing_token`,
`401 invalid_token`, `401 token_expired`, `403 scope_denied`.

### POST /agent-auth/v1/token/create

Create a new token family and return an access/refresh token pair.

Request:

```json
{"scopes": {"things:read": "allow", "things:write": "prompt"}}
```

Response (200):

```json
{
  "family_id": "fff",
  "access_token": "aa_xxx_yyy",
  "refresh_token": "rt_xxx_yyy",
  "scopes": {"things:read": "allow", "things:write": "prompt"},
  "expires_in": 900
}
```

Errors: `400 no_scopes` (empty or missing scopes), `400 invalid_tier` (tier not in `allow`/`prompt`/`deny`), `400 malformed_request`.

No authentication required. Trust boundary is the server's bind address (127.0.0.1 by default — see ADR 0006).

### GET /agent-auth/v1/token/list

Return all token families, including revoked ones.

Response (200): JSON array of family objects.

```json
[
  {"id": "fff", "scopes": {"things:read": "allow"}, "created_at": "2026-04-19T10:00:00Z", "revoked": false}
]
```

No authentication required.

### POST /agent-auth/v1/token/modify

Modify the scopes on an existing token family. Takes effect on the next `/validate` call — no new tokens are issued.

Request:

```json
{
  "family_id": "fff",
  "add_scopes": {"things:write": "allow"},
  "remove_scopes": ["things:read"],
  "set_tiers": {"things:write": "prompt"}
}
```

All modification fields are optional; at least one must be non-empty. `set_tiers` silently skips scope names that do not exist on the family.

Response (200):

```json
{"family_id": "fff", "scopes": {"things:write": "prompt"}}
```

Errors: `400 no_modifications`, `400 invalid_tier`, `400 malformed_request`, `404 family_not_found`, `409 family_revoked`. No authentication required.

### POST /agent-auth/v1/token/revoke

Revoke a token family, invalidating all its tokens. Idempotent: revoking an already-revoked family returns 200.

Request:

```json
{"family_id": "fff"}
```

Response (200):

```json
{"family_id": "fff", "revoked": true}
```

Errors: `400 malformed_request`, `404 family_not_found`. No authentication required.

### POST /agent-auth/v1/token/rotate

Revoke an existing token family and create a new one with the same scopes.

Request:

```json
{"family_id": "fff"}
```

Response (200):

```json
{
  "old_family_id": "fff",
  "new_family_id": "ggg",
  "access_token": "aa_xxx_yyy",
  "refresh_token": "rt_xxx_yyy",
  "scopes": {"things:read": "allow"},
  "expires_in": 900
}
```

Errors: `400 malformed_request`, `404 family_not_found`, `409 family_revoked`. No authentication required.

## Graceful shutdown

Both `agent-auth serve` and `things-bridge serve` install SIGTERM and
SIGINT handlers in `run_server`. On first signal the process:

1. Stops accepting new connections (`server.shutdown()` on a daemon
   thread — required because `BaseServer.shutdown` must not run on
   the `serve_forever` thread).
2. Drains in-flight requests: `ThreadingHTTPServer.daemon_threads` is
   set to `False` on both service classes so `server_close()` joins
   every active request thread before returning.
3. Runs service-specific cleanup — `agent-auth` calls
   `TokenStore.close()` which issues `PRAGMA wal_checkpoint(TRUNCATE)`
   on a fresh connection, so the next boot does not replay journalled
   writes.
4. Exits `0`.

A daemon watchdog thread bounds the whole sequence to
`shutdown_deadline_seconds` (default `5.0`, configurable per service
in `config.yaml`). If drain has not completed by then the watchdog
calls `os._exit(1)` so a hung request handler cannot hold the
process open past its container's `stop_grace_period`.

The default matches the `stop_grace_period: 5s` on each service in
`docker/docker-compose.yaml`. See
`design/decisions/0018-graceful-shutdown.md` for the rationale.

## Network Configuration

### Local (host only)

- agent-auth listens on `127.0.0.1:9100`
- App bridges listen on `127.0.0.1:9200` (and subsequent ports for additional bridges)
- CLIs call localhost directly

### Devcontainer

- agent-auth listens on `127.0.0.1:9100`
- App bridges listen on `127.0.0.1:9200`
- Docker port forwarding exposes host ports to the devcontainer
- CLIs use `host.docker.internal:9200` for bridge, `host.docker.internal:9100` for agent-auth

## Testing

### Unit tests

`tests/test_*.py` exercise individual modules in-process. Handler
edge cases (malformed JSON, unknown routes, oversize bodies, the
`/agent-auth/health` endpoint) are covered by in-process tests in
`tests/test_server.py` using a thread-local `AgentAuthServer`.

### Integration tests

`tests/integration/agent_auth/test_*.py` drive a containerised `agent-auth serve`
end-to-end over HTTP. Each test gets its own Docker Compose project
(named by a uuid), its own ephemeral host port, its own SQLite file,
and its own keyring — so concurrent test runs on the same host cannot
collide. Tests use only the public surface: the HTTP API and the
`agent-auth` CLI invoked inside the container via
`docker compose exec`. See `design/decisions/0004-docker-integration-tests.md`.

Run modes:

- `scripts/test.sh --unit` (default) — in-process tests only; no Docker
  required.
- `scripts/test.sh --integration` — container-backed tests; requires
  Docker.
- `scripts/test.sh --all` — both layers.

## Performance budget

`.claude/instructions/testing-standards.md` § Performance requires a
documented latency target for critical operations plus at least one
test that asserts the budget. This section pins the targets; the
assertion lives in `tests/test_perf_budget.py` behind a
`@pytest.mark.perf_budget` marker so the gate is discoverable by tag
and independently runnable (`pytest -m perf_budget`).

The agent hot path — the one every third-party request passes through
— is `POST /agent-auth/v1/validate`. A slow validate becomes a
per-request tax on every downstream bridge, so it carries the tightest
budget:

| Endpoint                            | Median (p50) | p95    | Rationale                                                                                                                                                                                                                                                                       |
| ----------------------------------- | ------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /agent-auth/v1/validate`      | 10 ms        | 50 ms  | HMAC verify + indexed SQLite read + audit-log append. Headroom over the measured local baseline so GitHub Actions / macOS CI noise does not flake. Budget is *allow-tier only*; prompt-tier latency is dominated by the notification plugin and is not a library-level concern. |
| `POST /agent-auth/v1/token/refresh` | 20 ms        | 100 ms | Mark-consumed + new-token-pair write under a transaction; inherently hotter than validate because it writes, not reads.                                                                                                                                                         |
| `POST /agent-auth/v1/token/create`  | 30 ms        | 150 ms | Management-side, low volume; budgeted generously because it also holds an encrypted scope write.                                                                                                                                                                                |

Measurement protocol: the perf-budget test drives the listed endpoint
against a throwaway in-process `AgentAuthServer` bound to `127.0.0.1:0`
(same fixture pattern the other handler-edge tests use), issues N=100
sequential requests, and asserts the median and p95 of the per-request
wall-clock duration do not exceed the numbers above. The budget is
deliberately sequential — concurrency-level throughput is out of scope
for a single-instance, single-user deployment.

The floor is a *never-loosen* signal, not a benchmark — it ratchets
**downward** as the implementation improves, never upward, per the
same policy as the coverage and mutation-score thresholds. Any commit
that raises it must include the measurement and an explicit
justification in the commit message body.

## Observability

The project follows the
[OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/),
pinned to
[v1.40.0](https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.40.0),
for HTTP-server metric names and HTTP-attribute log keys. The
rationale and deviations are recorded in
`design/decisions/0017-opentelemetry-semantic-conventions.md`. The
pin refers to semconv attribute names only; the project emits
Prometheus text and JSON-lines directly and does not depend on the
OpenTelemetry SDK or OTLP transport.

`GET /agent-auth/metrics` and `GET /things-bridge/metrics` emit
Prometheus text exposition (v0.0.4) gated by an
`<service>:metrics` scope, paralleling the `<service>:health` model.
The audit-log schema is pinned by contract tests in
`tests/test_audit_schema.py` and versioned via `SCHEMA_VERSION` in
`src/agent_auth/audit.py` (see "Audit log fields" below).

Three observable surfaces ship with each service: the audit log
(JSON-lines on disk), the operational streams (human-readable text
on stdout / stderr), and the Prometheus scrape endpoint
(`GET /<service>/metrics`). The rest of this section pins their
schema, routing, log levels, locations, rotation, and retention,
satisfying `.claude/instructions/service-design.md`'s
Observability-design standard.

### Log streams

Each surface has a distinct purpose and stability contract; mixing
them would break downstream expectations:

| Stream         | Format          | Destination                                              | Purpose                                                                                                 | Stability                                                                             |
| -------------- | --------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Audit log      | JSON-lines      | `$XDG_STATE_HOME/agent-auth/audit.log` (agent-auth only) | Security-relevant events for SIEM, compliance, forensics.                                               | Versioned via `schema_version`; contract-tested.                                      |
| Operational    | Human text      | stdout / stderr of the server or CLI process             | One-off messages — startup banner, shutdown notices, CLI user feedback, fatal errors before audit init. | Not versioned; phrasing may change without notice. Not for programmatic consumption.  |
| Metrics scrape | Prometheus text | `GET /<service>/metrics`                                 | Aggregate counters / histograms for dashboards and alerting.                                            | Metric names and labels documented in "HTTP server metrics" / "Domain metrics" below. |

things-bridge emits no dedicated audit log — every request it
handles traces back to agent-auth's audit trail via the delegated
validation call, so audit coverage is single-sourced there. The
audit envelope (OTel `service.name` / `service.version` resource
attributes alongside `schema_version` / `timestamp` / `event`) is
nonetheless shaped to work across services so any future emitter
ships with the same wire format; today that envelope carries a
constant `service.name = "agent-auth"`.

### Log levels

The project deliberately does *not* use Python's `logging` module
and therefore has no DEBUG / INFO / WARN / ERROR hierarchy. The
flat two-stream model reduces the surface where an operator must
configure log-level routing on a personal-use deployment:

| "Level"     | Goes where           | When it's emitted                                                          |
| ----------- | -------------------- | -------------------------------------------------------------------------- |
| Audit       | JSON-lines audit log | Every token lifecycle operation + every validation / JIT-approval outcome. |
| Operational | stdout               | Startup banner (service name + bound port), shutdown notices.              |
| Operational | stderr               | Shutdown-deadline overrun, CLI error messages, Python tracebacks on crash. |

DEBUG-style tracing (per-request spans, internal state dumps) is
not shipped. When a deeper trace is needed for a specific
investigation, reach for a debugger or add a targeted print in a
branch — do not introduce a persistent DEBUG channel, which would
create an auxiliary surface that can drift from the audit schema.

### Log location and rotation

| Stream      | Location                               | Rotation                                                                                                                                                                                                             |
| ----------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Audit log   | `$XDG_STATE_HOME/agent-auth/audit.log` | **Not rotated by the service.** The operator is expected to rotate via `logrotate`, `newsyslog`, or equivalent; agent-auth re-opens the log file via plain append on every write, so post-rotate truncation is safe. |
| Operational | stdout / stderr of the process         | Handled by whatever captures the process (systemd journal, launchd, container runtime). Not the service's concern.                                                                                                   |

`$XDG_STATE_HOME` falls back to `~/.local/state` on Linux and
`~/Library/Application Support` on macOS per the XDG base-directory
spec. The path is honoured by `Config.log_path`'s default; the
operator can override it in `config.yaml`.

### Retention policy

Retention is the operator's responsibility:

- **Audit log** — recommended minimum of 90 days for a
  personal-use deployment; extend per any applicable compliance
  obligations. The file is append-only; use `logrotate` (or host
  equivalent) to archive and optionally compress older segments.
  Automated pruning from within the service is intentionally out
  of scope — any retention policy would also need a tamper-evidence
  story that's beyond the project's assurance level (see
  `design/ASSURANCE.md`).
- **Operational logs** — best-effort. The service writes them to
  stdout / stderr and does not persist them; retention is whatever
  the process supervisor records.
- **Metrics** — not persisted by the service. Any Prometheus
  scraper records its own retention per its deployment config.

No message emitted by the service requires asynchronous operator
action — all actionable signals either return a non-2xx HTTP
status or fail the process with a non-zero exit code. A missing
`audit.log` at startup is non-fatal; the service creates it on
first write.

### HTTP server metrics

Emitted on `/metrics`. Metric names follow OTel semconv; Prometheus
exposition replaces `.` with `_` and appends units per the
Prometheus convention. The attribute set is a pragmatic subset of
semconv: `http.request.method` / `http.route` /
`http.response.status_code` are carried on the duration histogram;
`url.scheme` and `server.*` are omitted because both services bind
to a fixed host and speak HTTP only, so the attributes would add
cardinality with no distinguishing power.

| OTel metric name               | Prometheus name                        | Instrument (Prometheus type) | Attributes / labels              |
| ------------------------------ | -------------------------------------- | ---------------------------- | -------------------------------- |
| `http.server.request.duration` | `http_server_request_duration_seconds` | Histogram (histogram)        | `method`, `route`, `status_code` |
| `http.server.active_requests`  | `http_server_active_requests`          | UpDownCounter (gauge)        | `method`                         |

Histogram bucket boundaries (seconds): `0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10` — the OTel-recommended
HTTP-latency defaults.

### Domain metrics

Agent-auth emits three domain counters outside the OTel namespace;
things-bridge has no domain state of its own (authz denials and
Things-app failures fold into the `status_code` label on the HTTP
duration histogram).

| Prometheus name                        | Type    | Labels              | Notes                                                                                                                   |
| -------------------------------------- | ------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `agent_auth_token_operations_total`    | Counter | `operation`         | `operation` ∈ `{created, refreshed, reissued, revoked, rotated}`                                                        |
| `agent_auth_validation_outcomes_total` | Counter | `outcome`, `reason` | `outcome` ∈ `{allowed, denied}`; `reason` mirrors the `validation_denied` audit reasons, plus `ok` for the allowed path |
| `agent_auth_approval_outcomes_total`   | Counter | `outcome`           | `outcome` ∈ `{approved, denied}`                                                                                        |

The endpoint is authenticated under the `agent-auth:metrics` and
`things-bridge:metrics` scopes; unauthenticated probes return 401.
Token-family and per-token labels are deliberately excluded to
bound cardinality and to keep high-churn labels out of the audit
surface.

### Audit log fields

The audit log at `$XDG_STATE_HOME/agent-auth/audit.log` is JSON-lines.
The on-disk format is part of the project's public surface and is
versioned via the `schema_version` field emitted on every entry
(current value: `1`; constant `SCHEMA_VERSION` in
`src/agent_auth/audit.py`).

**Stability policy** — downstream consumers (SIEM, compliance,
forensics) can rely on the following guarantees within a given
`schema_version`:

- Adding a new optional field is non-breaking; the version stays the
  same.
- Adding a new `event` kind is non-breaking; the version stays the
  same.
- Renaming, removing, or re-typing an existing field is a breaking
  change; `SCHEMA_VERSION` must be bumped and the change announced
  in `CHANGELOG.md`.

Contract tests in `tests/test_audit_schema.py` pin every documented
event kind and fail if a field is renamed, removed, or re-typed
without a version bump.

Fields fall into three groups:

**Resource attributes (OTel resource semconv keys)** — identify the
emitter itself, not the request. Included on every entry so audit
trails can be joined across services or retained through a file move:

| Field             | Type   | Value                                                                                                                                                             |
| ----------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `service.name`    | string | `agent-auth`. Constant today — things-bridge has no dedicated audit log (see §Log streams). The field is retained in the envelope for future audit emitters.      |
| `service.version` | string | PEP 440 release version, read from `agent_auth.__version__` (i.e. `importlib.metadata.version("agent-auth")`). `0.0.0+unknown` when the package is not installed. |

**HTTP request attributes (OTel HTTP semconv keys)** — *reserved for
future events that originate from an HTTP request.* Not emitted today;
authorization decisions currently carry only domain fields plus the
resource envelope. Names and types below are the reservation; when
events begin populating them, they will follow the semconv HTTP
conventions verbatim:

| Field                       | Type   | Source (when emitted)                                                                                      |
| --------------------------- | ------ | ---------------------------------------------------------------------------------------------------------- |
| `http.request.method`       | string | e.g. `POST`                                                                                                |
| `http.route`                | string | templated path, e.g. `/agent-auth/token/modify` (metrics-safe, low cardinality)                            |
| `url.path`                  | string | actual request path with concrete IDs, e.g. `/agent-auth/token/modify` (forensics-useful for audit trails) |
| `http.response.status_code` | int    | HTTP response status                                                                                       |
| `url.scheme`                | string | `http` or `https`                                                                                          |
| `client.address`            | string | remote peer IP                                                                                             |
| `user_agent.original`       | string | verbatim `User-Agent` header                                                                               |
| `network.protocol.version`  | string | e.g. `1.1` or `2`; lets audits distinguish HTTP/1.1 from HTTP/2 sessions                                   |
| `server.address`            | string | local bind address                                                                                         |
| `server.port`               | int    | local bind port                                                                                            |

**Domain fields (project-namespaced)** — describe authorization
state, not HTTP mechanics. No OTel equivalent exists; these keep
their existing names:

| Field            | Type   | Description                                                                                                                                                                                                                    |
| ---------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `timestamp`      | string | ISO 8601 UTC emit time. Kept as `timestamp` (flat JSON, not an OTel LogRecord envelope).                                                                                                                                       |
| `schema_version` | int    | Wire-format version of the audit-log schema (currently `1`). See the stability policy above.                                                                                                                                   |
| `event`          | string | Discriminator — `validation_allowed`, `validation_denied`, `token_created`, `token_refreshed`, `token_reissued`, `token_revoked`, `token_rotated`, `scopes_modified`, `reissue_denied`, `approval_granted`, `approval_denied`. |
| `token_id`       | string | Opaque token identifier.                                                                                                                                                                                                       |
| `family_id`      | string | Opaque token-family identifier.                                                                                                                                                                                                |
| `scope`          | string | The single requested scope.                                                                                                                                                                                                    |
| `scopes`         | list   | Scopes on a family (on create / modify events).                                                                                                                                                                                |
| `tier`           | string | `allow`, `prompt`, or `deny`.                                                                                                                                                                                                  |
| `grant_type`     | string | JIT grant flavour on a `prompt`-tier approval.                                                                                                                                                                                 |
| `reason`         | string | Denial reason code on `validation_denied` / `reissue_denied`.                                                                                                                                                                  |

Log-level policy, log location, rotation, and retention are
documented in the subsections above.

## Rate limiting and request budgets

Both services run loopback-only by default (`127.0.0.1`) and are
single-user on a host. `design/decisions/0022-rate-limiting-posture.md`
records the decision to **defer application-layer rate limiting**
for 1.0; the guards that remain are the 1 MiB request-body cap
(`AgentAuthHandler.MAX_BODY_SIZE`), the 128-byte id-segment cap
(`ThingsBridgeHandler._safe_id`), and `ApprovalManager`'s implicit
per-family serialisation of JIT approvals via the notification
plugin's blocking contract.

Expected request rate and ceiling per endpoint on a typical
single-operator deployment:

| Endpoint                                                  | Expected rate (steady)      | Ceiling (short burst) | Notes                                                                    |
| --------------------------------------------------------- | --------------------------- | --------------------- | ------------------------------------------------------------------------ |
| `POST /agent-auth/v1/validate`                            | ≲ 10 / min per active agent | 60 / min              | One call per Things-bridge request; scripted agents are the main source. |
| `POST /agent-auth/v1/token/refresh`                       | ≲ 4 / hour per family       | 20 / hour             | Access tokens default to 15 min TTL, so 4/hour is the natural ceiling.   |
| `POST /agent-auth/v1/token/reissue`                       | ≲ 1 / day per family        | 5 / day               | Gated by JIT approval; burst unlikely given human-in-the-loop.           |
| `POST /agent-auth/v1/token/{create,modify,revoke,rotate}` | ≲ 1 / day                   | 50 / day              | Operator-driven management.                                              |
| `GET /agent-auth/v1/token/{list,status}`                  | ≲ 10 / min                  | 120 / min             | Operator-driven; management UIs may poll.                                |
| `GET /agent-auth/health`                                  | 1 / 10 s (probe)            | 1 / s                 | Liveness probes.                                                         |
| `GET /agent-auth/metrics`                                 | 1 / 15–60 s (scrape)        | 1 / 5 s               | Prometheus scrape.                                                       |
| `GET /things-bridge/v1/*` (read)                          | ≲ 10 / min per active agent | 60 / min              | AppleScript subprocess is the bottleneck, not the bridge.                |
| `GET /things-bridge/health`, `/things-bridge/metrics`     | 1 / 10–60 s                 | 1 / s                 | Same probe / scrape budget as agent-auth.                                |

"Ceiling" is an observational target (what we expect to *see* in
normal operation) rather than an enforced limit. Exceeding it
during production use is a signal to investigate — a looping
agent, a runaway polling loop, or a legitimate workflow change —
not a condition to refuse.

## Key loss and recovery

The signing and encryption keys are stored only in the system
keyring. If that keyring is wiped or inaccessible (fresh OS
install, keychain reset, new host, corrupted macOS Keychain entry)
while the token store on disk persists, silently regenerating a
new key pair would strand every live token and render encrypted
columns unreadable — and the operator would have no signal that
anything had changed until the next call failed.

### Detection

`agent_auth.keys.check_key_integrity(db_path, key_manager)` runs
before any `get_or_create_*` call in `agent-auth`'s CLI
entrypoint (`_init_services`). It opens the token-store DB
read-only (no encryption key required — `token_families` is not
a field-encrypted column) and raises `KeyLossError` when:

- the DB file exists, and
- the `token_families` table has at least one row, and
- either the signing or the encryption key is absent from the
  keyring.

The DB-absent and DB-empty paths are the legitimate first-install
and clean-start cases; the check stays silent and startup
proceeds to `get_or_create_*`.

### Operator-facing error

`KeyLossError`'s message names the missing key(s), the DB path,
and the two recovery options:

- **Restore the keyring entry.** If the operator has a backup of
  the `agent-auth` service entry (for example, via macOS Time
  Machine restore of `~/Library/Keychains`), reinstalling it
  brings the existing tokens back to life. No tooling is shipped
  for this — it is operator-driven.
- **Delete the token store.** Remove `tokens.db` and its
  `-wal` / `-shm` siblings under `$XDG_DATA_HOME/agent-auth/`.
  The next launch generates a fresh key pair and a fresh DB,
  which invalidates every previously issued access and refresh
  token. Clients must be reissued from scratch.

The CLI catches `KeyLossError` at `main()` and prints the message
verbatim to stderr with exit status 2 — Python tracebacks would
bury the recovery instructions.

### No backup tool in 1.0

agent-auth deliberately does **not** ship a backup or export tool
for the keys. Any first-party backup path would:

- introduce a secondary store for 32-byte secrets, widening the
  attack surface; and
- need its own tamper-evidence, key-wrapping, and restore-
  verification story that the QM/SIL declaration in
  `design/ASSURANCE.md` does not cover.

For a personal-use deployment the system keyring's own backup
story (macOS Time Machine of `~/Library/Keychains`; `seahorse`
export on Linux) is the intended path. This is revisitable if a
future multi-user or remote-operator posture makes a first-party
backup tool necessary.

### Known gaps

- Byte-for-byte corruption of the keyring entry (not absence) is
  not detected: `check_key_integrity` verifies presence, not
  validity. A corrupted entry surfaces later as a signature-
  verification failure (`TokenInvalidError`) or an `AESGCM`
  decryption `InvalidTag` error on the first authenticated
  request. The operator-visible symptom is the same — every
  live token suddenly looks invalid — and so is the mitigation
  path (restore or wipe).
- The check runs exactly once at startup. Key rotation while the
  server is running is out of scope (`agent-auth` does not
  implement key rotation in 1.0).

## Security Considerations

- The signing key is stored in the system keyring (macOS Keychain or libsecret/gnome-keyring), never as a plaintext file. Only agent-auth reads it.
- The token store (SQLite) uses field-level encryption (AES-256-GCM) for sensitive columns, with the encryption key stored in the system keyring. Only agent-auth accesses it.
- Bridges never see the signing key or token store — they delegate all auth decisions to agent-auth.
- CLIs are untrusted. They cannot escalate scopes. A stolen access token is useful for at most 15 minutes. A stolen refresh token is detected on reuse and triggers family revocation.
- All servers bind to `127.0.0.1`. Devcontainer access is provided via Docker port forwarding, not by binding to `0.0.0.0`.
- JIT approval notifications include a human-readable description of the operation so the user can make an informed decision.
- All token operations and authorization decisions are audit logged.
