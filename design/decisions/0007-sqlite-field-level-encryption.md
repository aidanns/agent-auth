<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0007 — SQLite with field-level AES-256-GCM encryption

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

The token store holds the primary material an attacker needs to
impersonate a user to agent-auth — HMAC signatures for every live
access and refresh token, plus the scope grants tied to each family.
It lives on disk on the host, where:

- The user's other tools, backup agents, Time Machine snapshots, and
  cloud sync daemons can all reach it.
- A compromised process running as the user (a VS Code extension, a
  browser extension spawning a helper) can read arbitrary files under
  `$HOME`.

The threat model therefore assumes the attacker can exfiltrate the
SQLite file. What's required is that the file alone is not enough to
forge or validate tokens. At the same time, the server itself must
stay ergonomic — queries by token ID and family ID must remain
efficient, timestamps must remain queryable for expiry sweeps, and the
audit log of token operations must remain analysable.

## Considered alternatives

### SQLCipher (whole-DB encryption)

Encrypt the entire database page layer. Standard, well-trodden
approach.

**Rejected** because:

- Adds a non-pure-Python C dependency that doesn't ship on the PyPI
  `sqlite3` wheel. Installation story on macOS/Linux diverges.
- Coarse-grained: a compromised server process has to hold the key
  for the life of the process anyway, so the attacker who gets code
  execution inside agent-auth still reads everything. The attacker
  we're defending against is the *file exfiltrator*, and a
  field-level scheme handles that case without giving up SQLite's
  standard tooling (`.dump`, `sqlite3` REPL, the built-in
  `sqlite3` module).

### Encrypt the whole row, decrypt on read

Serialise each row to JSON, encrypt, store a single ciphertext blob.

**Rejected** because:

- Breaks indexing — a family-wide revoke sweep or an expired-token
  GC would have to decrypt every row.
- Opaque rows defeat low-tech triage (`sqlite3 tokens.db .schema`).

### Plaintext DB, rely on file permissions only

**Rejected** because the threat model explicitly assumes the DB can
be exfiltrated. File permissions protect only against *same-host,
different-user* access, which is not the attack we're worried about.

## Decision

Use SQLite at `$XDG_DATA_HOME/agent-auth/tokens.db` (see ADR 0012)
with AES-256-GCM field-level encryption on the sensitive columns
only. Concretely (see the schema in `src/agent_auth/store.py`):

- `token_families` stores `id`, `created_at`, and `revoked` in
  plaintext (so family-revocation sweeps and audit queries remain
  efficient). `scopes` is an encrypted `BLOB`.
- `tokens` stores `id`, `family_id`, `type`, `expires_at`, and
  `consumed` in plaintext (so expiry sweeps, foreign-key joins, and
  reuse detection remain efficient). `hmac_signature` is an
  encrypted `BLOB`.
- Sensitive columns are encrypted with AES-256-GCM via the
  `cryptography` library's `AESGCM` primitive. Marked with `(E)` in
  the `DESIGN.md` schema tables.
- The encryption key is a 32-byte AES key held in the system keyring
  (see ADR 0008), generated on first startup.
- Encrypt / decrypt helpers live in `src/agent_auth/crypto.py`;
  `src/agent_auth/store.py` wraps every DB write/read through them.

## Consequences

- An attacker with the SQLite file but not the keyring can see *that*
  tokens exist (and when they expire), but cannot forge them or read
  the scope grants.
- The server holds the encryption key in memory for its lifetime.
  A compromised server process reads plaintext; that's the accepted
  threat boundary.
- Expiry sweeps, family-wide revocation, and reuse detection all
  operate on plaintext columns — the encryption scheme does not
  degrade those paths.
- Every sensitive column write is `encrypt_field(...)` producing a
  `nonce || ciphertext || tag` blob stored as a SQLite `BLOB`; every
  read is the reverse. Acceptable overhead at agent-auth's expected
  request rates (human-driven, not bulk).
- `cryptography` is a C-extension dependency; it's listed in
  `pyproject.toml` and picks up wheels on all supported platforms.
- Changing the encryption key (rotation) is not automated — the
  store is rekeyed by wiping and reissuing all tokens. Tracked as a
  follow-up if it becomes necessary.
