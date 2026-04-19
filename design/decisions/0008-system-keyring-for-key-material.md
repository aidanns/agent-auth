# ADR 0008 — System keyring for signing and encryption keys

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

agent-auth holds two long-lived secrets in production:

1. The **HMAC signing key** used to sign and verify token strings
   (see ADR 0006). Anyone with this key can forge valid access and
   refresh tokens for any family.
2. The **AES-256-GCM encryption key** used for field-level
   encryption in the token store (see ADR 0007). Anyone with this
   key plus the SQLite file can read every token's signature and
   every family's scope grants.

Both are 32-byte symmetric keys. They must survive server restarts
(otherwise every client's existing tokens are invalidated) and must
not share disk location with the SQLite store (otherwise the "attacker
with the DB" threat-model assumption is violated).

## Considered alternatives

### Keys in config file at a different path

Store keys as hex-encoded strings in a YAML file under
`$XDG_CONFIG_HOME/agent-auth/`, separate from the SQLite file in
`$XDG_DATA_HOME/agent-auth/`.

**Rejected** because:

- Path separation defeats *co-location*, not *exfiltration*. An
  attacker who walks the user's home directory picks up both paths.
- File permissions (`0600`) protect against same-host other-user,
  which isn't the threat.
- Forces agent-auth to own key-file lifecycle (atomic writes, umask,
  backup opt-out). The OS already provides this for keyring entries.

### HashiCorp Vault / cloud KMS

**Rejected** as over-scoped for a local-host tool. Adds network
dependency and a second trust domain.

### Per-startup ephemeral key

Generate a fresh key at server start, re-issue tokens on restart.

**Rejected** because it makes restarting the server a breaking
operation for every connected client — unacceptable usability
regression.

## Decision

Store both keys in the system keyring, behind a narrow wrapper in
`src/agent_auth/keys.py`:

- `KeyManager.get_or_create_signing_key()` — returns the signing
  key, generating 32 bytes of CSPRNG and persisting to the keyring
  if absent.
- `KeyManager.get_or_create_encryption_key()` — same shape for the
  AES key.

The keys are typed (`SigningKey` and `EncryptionKey` newtypes) so
they cannot be passed to the wrong primitive at type-check time
(static check only — Python has no compile-time type enforcement). The
keyring backend is selected automatically:

- **macOS Keychain** on macOS hosts.
- **libsecret / gnome-keyring** on Linux hosts (including the
  devcontainer, where the Secret Service D-Bus backend is available).
- **File-backed fallback (`keyrings.alt`)** inside the integration-test
  container, where no interactive backend is present. Only used in
  the test image (see ADR 0004 for the plumbing) — never in production
  installs.

The CLI client reuses the same keyring abstraction for its own
credential storage, but with different entry names and a
`--credential-store=file` escape hatch (see DESIGN.md "CLI Credential
Storage").

## Consequences

- Key material never lives on disk in a form the file-level attacker
  can read. On macOS the Keychain applies additional ACLs; on Linux
  the D-Bus layer requires the desktop session to be unlocked.
- Installing / moving the server between hosts requires the operator
  to transfer the keyring entries explicitly — there's no "copy one
  file" migration. Acceptable: this is a security property, not a
  friction to smooth over.
- The integration-test Docker image uses `keyrings.alt` with
  file-backed storage so tests can run without a desktop session.
  That backend is explicitly limited to the test image and is not
  on the production installation path.
- A compromised user session on the host can prompt the keyring to
  unlock and read the keys. That is within the threat boundary
  (same-user same-host code execution); defence is via audit
  logging of every token operation, not via the keyring.
- Key rotation is manual: delete the keyring entry, restart the
  server, reissue all tokens. Tracked as a follow-up if / when it
  becomes necessary.
