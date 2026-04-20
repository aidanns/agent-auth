<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0011 — Refresh-token reuse triggers family revocation

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

Access tokens are short-lived (default 15 minutes) so a compromised
access token has a bounded usefulness window. Refresh tokens, by
contrast, are long-lived (default 8 hours) and powerful: holding one
is equivalent to holding a current credential for the whole duration.

The threat: a refresh token leaks (sloppy logging, backup exposure,
credential-stealing malware). Without detection, the attacker can
silently refresh forever, producing a continuous stream of valid
access tokens. Scope modification and manual rotation help, but only
if the user *notices* the compromise — something a silent attacker is
motivated to avoid.

OAuth 2.0's refresh-token rotation family (RFC 6819 §5.2.2.3,
OAuth 2.1 draft §6.1) gives us the standard hook: make refresh tokens
single-use, and use a second refresh attempt on the same token as a
detector.

## Considered alternatives

### Long-lived non-rotating refresh tokens

Simpler client code; accept the detection gap.

**Rejected** because the detection gap *is* the reason this model
exists. Without rotation, a stolen refresh token is indistinguishable
from a live one.

### Short-lived refresh tokens with no reuse detection

Reduce refresh TTL to 15 minutes, force the client through
re-issuance frequently.

**Rejected** because re-issuance requires JIT approval (see below).
Prompting the user every 15 minutes defeats the purpose of having
refresh tokens at all.

## Decision

Refresh tokens are single-use. The store records a `consumed` flag
per token; the first successful `POST /agent-auth/token/refresh`
flips it atomically:

- On success: return a new access/refresh token pair in the same
  family; the old refresh token is marked consumed.
- On second use of the same refresh token: the `mark_consumed`
  transaction reports it was already consumed. agent-auth treats
  this as a reuse event and calls `mark_family_revoked` on the
  entire token family. Both the attacker's and the legitimate
  client's in-flight and future tokens are now invalid.

The legitimate client detects revocation via 401 with
`{"error": "refresh_token_reuse_detected"}` on the next refresh (or
`{"error": "token_revoked"}` on a validate call against an
already-revoked family — see `_handle_validate` in
`src/agent_auth/server.py`) and falls through to the re-issuance
path:

- `POST /agent-auth/token/reissue` with the family ID blocks on JIT
  approval.
- On approval, a fresh access/refresh pair is issued in the
  **same** family (the family ID is preserved). The new tokens
  inherit the family's existing scopes.
- Re-issuance is blocked if the family was revoked because the
  refresh-token reuse detection fired — the user must explicitly
  create a new token via the CLI. Re-issuance is only available
  when the family's refresh token *expired*, not when it was
  consumed-via-reuse.

The logic is implemented in `src/agent_auth/server.py`
(`POST /agent-auth/token/refresh` handler — see
`store.mark_consumed` and `store.mark_family_revoked`).

## Consequences

- A stolen refresh token grants the attacker exactly one refresh
  before the legitimate client's next refresh (or vice versa) blows
  the whole family away. Both parties are then locked out until the
  user approves re-issuance on the host.
- The user experiences the lock-out as a JIT approval prompt
  describing "refresh token reuse detected; re-issue tokens?" The
  notification plugin surfaces the family ID so the user can
  correlate with their own expectations of what's logged in.
- Clients must handle the reuse-detected error distinctly from the
  expired error. The CLI helper library does this centrally so
  individual commands don't re-implement the logic.
- Re-issuance requires physical presence at the host, so a refresh-
  token thief can't trigger re-issuance even if they happen to also
  know the family ID.
- Edge case: the legitimate client and a legitimate backup CLI on
  the same host both try to refresh in a close race. One succeeds;
  the other hits the consumed state and revokes the family. This is
  accepted collateral — the alternative (letting parallel refresh
  succeed) loses reuse detection. A real-world workaround is to
  provision separate token families for parallel clients.
- Audit log records every revocation with reason
  (`refresh_reuse_detected`, `token_modify`, `manual_rotate`), so
  the user can distinguish an attack from a self-inflicted wipe.
