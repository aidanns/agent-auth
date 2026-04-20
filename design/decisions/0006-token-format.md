<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0006 — Token format

## Status

Accepted — 2026-04-19.

Backfilled ADR: the decision was made when the token store was first
implemented; this record captures the rationale after the fact.

## Context

agent-auth issues bearer tokens that bridges forward to the
`/agent-auth/validate` endpoint. The format has to:

1. Let the server tell access and refresh tokens apart on the wire so
   a mistakenly-presented refresh token is rejected at the parse
   layer rather than after an expensive database lookup.
2. Survive an attacker with the SQLite token store but *not* the
   signing key — the token they forge must not validate.
3. Be trivial to log and debug without leaking secrets. Opaque opaque
   blobs (a random 64-byte string keyed by ID in the DB) would force
   log redaction everywhere tokens surface; self-describing strings
   carry their own provenance.
4. Stay short enough to paste in a shell and pass around as a CLI
   argument.

## Considered alternatives

### Random opaque bearer tokens (DB lookup on every validate)

Generate 32 bytes of CSPRNG output, base64url-encode, store the
hash in the DB, validate by hashing and looking up.

**Rejected** because:

- Requires a DB round-trip even to decide whether the string is
  syntactically a token of ours. Bridges routinely see noise
  (expired tokens, typos, stale `.env` files) — parsing them out at
  the string level is cheaper and leaks less to disk.
- No wire-level access/refresh disambiguation.
- Doesn't satisfy the "attacker with DB but not key can't forge"
  property — if an attacker has the DB, they also have the stored
  hash's preimage target and only need to brute-force the input
  space, not the key space.

### JWT (signed or encrypted)

**Rejected** because:

- Claims payload carries scope metadata in the token, meaning a
  refreshed-or-modified token has to be reissued to change scopes.
  agent-auth deliberately keeps scope state in the DB so
  `token modify` takes effect on the next validate without
  re-issuing (see DESIGN.md "Scope modification").
- Ecosystem complexity (alg confusion, `none` alg, library CVEs) is
  not worth it for a tool with exactly one issuer and one verifier,
  both in the same process.

## Decision

Tokens are self-describing strings of the shape:

```
<prefix>_<token-id>_<hmac-signature>
```

where:

- `<prefix>` is `aa` for access tokens and `rt` for refresh tokens
  (`PREFIX_ACCESS` / `PREFIX_REFRESH` in `src/agent_auth/tokens.py`).
- `<token-id>` is `uuid.uuid4().hex` (a 32-character hex string).
- `<hmac-signature>` is `HMAC-SHA256(signing_key, prefix + "_" + token_id)`
  hex-encoded.

The prefix is covered by the signature. An attacker who knows a valid
access token can't downgrade it to a refresh token (or vice versa)
without recomputing the HMAC under the signing key. The signing key
lives in the system keyring (see ADR 0008), never on disk next to the
token store.

## Consequences

- Token validation is a single HMAC verify plus a DB lookup keyed on
  `token_id`. The HMAC short-circuits invalid strings before the DB
  is touched.
- Scope changes do not require reissuing tokens — scopes live in
  `token_families`, keyed by family ID, and are loaded on every
  validate (see ADR 0010).
- The token format is part of the public surface. Clients and
  bridges parse it on sight (for error messages and for routing
  wire-level errors before the server is called). Changing the
  shape is a breaking change requiring dual-support.
- A stolen access token is usable until it expires (default 15
  minutes). A stolen refresh token is subject to reuse detection
  (ADR 0011).
- The signature covers `prefix_token-id` rather than the raw
  `token_id` specifically to bind the role to the signature; this
  is a minor defence against future format extensions that might
  otherwise share a signing domain.
