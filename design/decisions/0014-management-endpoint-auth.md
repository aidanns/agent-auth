# ADR 0014: Management Endpoints Require a Management Bearer Token

## Context

Issue #3 adds HTTP endpoints for token lifecycle management (create, list,
modify, revoke, rotate). These are privileged operations — they can create new
tokens or cancel existing ones. The runtime endpoints (`/validate`,
`/token/refresh`, `/token/reissue`, `/token/status`) require a valid bearer
token issued by the server itself. The management endpoints need a trust model.

The alternatives considered:

1. **No additional auth** — trust is derived from network access, which is
   scoped to localhost (127.0.0.1) by default. Simple, but provides no
   programmatic identity for audit logging, and offers no gate if the bind
   address is changed to a non-loopback interface.
2. **Bearer token with a management scope** — a token carrying
   `agent-auth:manage=allow` gates all management calls. The bootstrapping
   challenge (you need a token to create the first token) is resolved by
   creating the initial management token directly via the store on server
   startup, storing the refresh token in the OS keyring alongside the
   signing and encryption keys. Operators retrieve the refresh token via
   `agent-auth management-token show`. External clients exchange it for an
   access token via the standard `/token/refresh` endpoint.
3. **Separate management API key** — a static opaque key stored in config or
   keyring. Adds friction (separate key format, rotation story) without
   integrating with the existing token model.

## Decision

Management endpoints require an `Authorization: Bearer <token>` header
carrying an access token whose family has `agent-auth:manage=allow` in its
scopes. Only `allow`-tier management tokens are accepted; `prompt`-tier JIT
approval for management operations is left as a future enhancement.

On first startup, `run_server` calls `_bootstrap_management_token` which
checks the keyring for an existing management refresh token. If none is found
(or the stored token's family has been revoked), a new token family is created
directly via the store and the refresh token is persisted to the keyring.

The management token family is excluded from `GET /token/list` responses so it
does not appear in external clients' token inventories.

## Consequences

- Management endpoints return 401 if no `Authorization` header is present and
  403 if the token exists but lacks `agent-auth:manage=allow` scope.
- The `agent-auth:manage` scope is reserved; no user-created token should
  carry it. Future work: enforce this at creation time.
- `agent-auth management-token show` exposes the management refresh token from
  the keyring so operators can hand it to external clients.
- If the server is restarted after the management token family is rotated or
  revoked externally, `_bootstrap_management_token` detects the revoked state
  and creates a fresh family automatically.
- Access tokens expire (default 900 s). External clients must refresh via
  `/token/refresh` before each management session or when they receive 401.
- The `prompt`-tier JIT path for management operations is not yet wired; a
  management token with `agent-auth:manage=prompt` is currently rejected
  (treated as scope_denied). This will be addressed in a follow-up issue.
