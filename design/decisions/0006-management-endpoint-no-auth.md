# ADR 0006: Management Endpoints Carry No Additional Authentication

## Context

Issue #3 adds HTTP endpoints for token lifecycle management (create, list,
modify, revoke, rotate). These are privileged operations — they can create new
tokens or cancel existing ones. The runtime endpoints (`/validate`,
`/token/refresh`, `/token/reissue`, `/token/status`) require a valid bearer
token issued by the server itself. The management endpoints need a trust model.

The alternatives considered:

1. **No additional auth** — trust is derived from network access, which is
   scoped to localhost (127.0.0.1) by default. Anyone who can reach the server
   is already on the host and could run the CLI directly.
2. **Bearer token with a management scope** — a pre-existing token carrying
   `agent-auth:manage` would gate all management calls. This creates a
   chicken-and-egg problem: the first token must still be created through some
   other mechanism (the CLI), and there is no bootstrapping story without it.
3. **Separate management API key** — a static key stored in config or keyring.
   Adds friction (key distribution, rotation) without meaningfully improving
   the security posture for a local daemon whose threat model is already
   bounded by host access.

## Decision

Management endpoints carry no additional authentication. The trust boundary is
the server's bind address: the default `127.0.0.1` restricts callers to the
local host, which is the same trust level as running the CLI directly.

## Consequences

- Any process on the host can call the management endpoints without a token.
  This matches the CLI's trust model (any user who can exec the CLI can manage
  tokens).
- If the server is ever reconfigured to bind to a non-loopback address,
  management endpoints become network-accessible with no auth gate. Operators
  who expose the server on a non-local interface must be aware of this risk.
  A firewall or reverse proxy with its own auth layer is required in that case.
- The bootstrapping story remains simple: `agent-auth token create` (CLI) or
  `POST /agent-auth/token/create` (HTTP) both work without any pre-existing
  credential.
- If a management token model is added in the future, the scope name
  `agent-auth:manage` is reserved for that purpose.
