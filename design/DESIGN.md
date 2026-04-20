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

| Method | Path                                                     | Scope                  | Description                                   |
| ------ | -------------------------------------------------------- | ---------------------- | --------------------------------------------- |
| GET    | `/things-bridge/todos?list=&project=&area=&tag=&status=` | `things:read`          | List todos, optionally filtered               |
| GET    | `/things-bridge/todos/{id}`                              | `things:read`          | Fetch one todo by Things id                   |
| GET    | `/things-bridge/projects?area=`                          | `things:read`          | List projects, optionally filtered by area id |
| GET    | `/things-bridge/projects/{id}`                           | `things:read`          | Fetch one project by Things id                |
| GET    | `/things-bridge/areas`                                   | `things:read`          | List all areas                                |
| GET    | `/things-bridge/areas/{id}`                              | `things:read`          | Fetch one area by Things id                   |
| GET    | `/things-bridge/health`                                  | `things-bridge:health` | Liveness / readiness probe                    |

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
POST /agent-auth/token/refresh
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
POST /agent-auth/token/reissue
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
    → POST http://localhost:9100/agent-auth/validate
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
    → POST http://host:9100/agent-auth/token/refresh
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
    → POST http://host:9100/agent-auth/token/refresh
      {"refresh_token": "rt_xxx_yyy"}
    ← 401 {"error": "refresh_token_expired"}

    → POST http://host:9100/agent-auth/token/reissue
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
    → POST http://localhost:9100/agent-auth/validate
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

## agent-auth HTTP API

All endpoints are prefixed with `/agent-auth/` to allow hosting behind a shared reverse proxy alongside bridge servers.

### POST /agent-auth/validate

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

### POST /agent-auth/token/refresh

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

### POST /agent-auth/token/reissue

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

### GET /agent-auth/token/status

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
`POST /agent-auth/token/refresh` before calling management endpoints. See
[ADR 0014](decisions/0014-management-endpoint-auth.md) for the rationale.

Errors returned when auth is missing or invalid: `401 missing_token`,
`401 invalid_token`, `401 token_expired`, `403 scope_denied`.

### POST /agent-auth/token/create

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

### GET /agent-auth/token/list

Return all token families, including revoked ones.

Response (200): JSON array of family objects.

```json
[
  {"id": "fff", "scopes": {"things:read": "allow"}, "created_at": "2026-04-19T10:00:00Z", "revoked": false}
]
```

No authentication required.

### POST /agent-auth/token/modify

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

### POST /agent-auth/token/revoke

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

### POST /agent-auth/token/rotate

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

`tests/integration/test_*.py` drive a containerised `agent-auth serve`
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

## Observability

The project follows the
[OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/),
pinned to
[v1.40.0](https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.40.0),
for HTTP-server metric names and HTTP-attribute log keys. The
rationale and deviations are recorded in
`design/decisions/0015-opentelemetry-semantic-conventions.md`. The
pin refers to semconv attribute names only; the project emits
Prometheus text and JSON-lines directly and does not depend on the
OpenTelemetry SDK or OTLP transport.

`GET /agent-auth/metrics` and `GET /things-bridge/metrics` are not
yet implemented (tracked in #26). The audit log schema is not yet
pinned by contract tests (tracked in #20). Log-level policy and
retention policy are deferred to the dedicated observability design
document (tracked in #33), which will also hold the full metrics
catalogue. This section pins the naming standard those efforts
build against; it does not yet satisfy
`.claude/instructions/service-design.md`'s Observability-design
standard in full — the missing log-level and retention pieces are
deliberately scoped to #33.

### HTTP server metrics

Emitted on `/metrics` once #26 lands. Metric names follow OTel
semconv; Prometheus exposition replaces `.` with `_` and appends
units per the Prometheus convention.

| OTel metric name               | Prometheus name                        | Instrument (Prometheus type) | Attributes / labels                                                                                                                                         |
| ------------------------------ | -------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `http.server.request.duration` | `http_server_request_duration_seconds` | Histogram (histogram)        | `http.request.method`, `http.route`, `url.scheme`, `http.response.status_code` (on non-error), `error.type` (on error)                                      |
| `http.server.active_requests`  | `http_server_active_requests`          | UpDownCounter (gauge)        | `http.request.method`, `url.scheme` (required); `server.address`, `server.port` (opt-in per semconv; emitted because local bind address varies per service) |

Domain counters for validation outcomes, token operations, and JIT
approval outcomes have no OTel equivalent and will use
project-namespaced names (e.g. prefixed `agent_auth_` /
`things_bridge_`). The specific metric names and label sets are
designed with #26 when the metrics endpoint lands; this section
only pins that they stay outside the OTel namespace.

### Audit log fields

The audit log at `$XDG_STATE_HOME/agent-auth/audit.log` is JSON-lines.
Fields fall into two groups:

**HTTP request attributes (OTel HTTP semconv keys)** — populated on
events that originated from an HTTP request. Names and types follow
the semconv HTTP conventions:

| Field                       | Type   | Source                                                                                                     |
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

**Resource attributes (OTel resource semconv keys)** — identify the
emitter itself, not the request. Included on every line so audit
trails can be joined across services:

| Field             | Type   | Source                          |
| ----------------- | ------ | ------------------------------- |
| `service.name`    | string | `agent-auth` or `things-bridge` |
| `service.version` | string | PEP 440 release version         |

**Domain fields (project-namespaced)** — describe authorization
state, not HTTP mechanics. No OTel equivalent exists; these keep
their existing names:

| Field        | Type   | Description                                                                                                                                                            |
| ------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `timestamp`  | string | ISO 8601 UTC emit time. Kept as `timestamp` (flat JSON, not an OTel LogRecord envelope).                                                                               |
| `event`      | string | Discriminator — `validation_allowed`, `validation_denied`, `token_created`, `token_refreshed`, `token_reissued`, `token_revoked`, `scopes_modified`, `reissue_denied`. |
| `token_id`   | string | Opaque token identifier.                                                                                                                                               |
| `family_id`  | string | Opaque token-family identifier.                                                                                                                                        |
| `scope`      | string | The single requested scope.                                                                                                                                            |
| `scopes`     | list   | Scopes on a family (on create / modify events).                                                                                                                        |
| `tier`       | string | `allow`, `prompt`, or `deny`.                                                                                                                                          |
| `grant_type` | string | JIT grant flavour on a `prompt`-tier approval.                                                                                                                         |
| `reason`     | string | Denial reason code on `validation_denied` / `reissue_denied`.                                                                                                          |

Contract tests pinning the schema (#20) and the dedicated
observability design (#33) extend this mapping.

## Security Considerations

- The signing key is stored in the system keyring (macOS Keychain or libsecret/gnome-keyring), never as a plaintext file. Only agent-auth reads it.
- The token store (SQLite) uses field-level encryption (AES-256-GCM) for sensitive columns, with the encryption key stored in the system keyring. Only agent-auth accesses it.
- Bridges never see the signing key or token store — they delegate all auth decisions to agent-auth.
- CLIs are untrusted. They cannot escalate scopes. A stolen access token is useful for at most 15 minutes. A stolen refresh token is detected on reuse and triggers family revocation.
- All servers bind to `127.0.0.1`. Devcontainer access is provided via Docker port forwarding, not by binding to `0.0.0.0`.
- JIT approval notifications include a human-readable description of the operation so the user can make an informed decision.
- All token operations and authorization decisions are audit logged.
