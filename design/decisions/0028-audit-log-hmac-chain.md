<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0028 — HMAC-chained audit log for tamper-evident integrity

## Status

Accepted — 2026-04-23.

## Context

The audit log at `$XDG_STATE_HOME/agent-auth/audit.log` records every
token lifecycle operation and every authorization decision. It is
append-only, JSON-lines, and documented as a public contract (see
ADR 0024 for the envelope). NIST SP 800-53 AU-9 (*Protection of
Audit Information*) is listed as "Partial" in `SECURITY.md` because
nothing prevents a privileged local attacker — or a post-compromise
attacker with `uid 0` — from silently editing or deleting entries to
erase their tracks. The threat-model table calls out this gap as the
Repudiation row; issue [#102] asked to close it.

Constraint: we cannot fix this without a key that is not stored
alongside the log file. If the integrity key lives on disk next to
the log, any attacker who can edit the log can edit the key and
recompute the integrity check. The existing `agent_auth.keys`
module already parks the HMAC signing key and the AES-256-GCM
encryption key in the OS keyring — we have a place to put an
integrity key that is out of the log file's reach.

Further constraint: schema stability. The envelope is contract-tested
by `tests/test_audit_schema.py` and the `schema_version` field's
stability policy says a new required field is a breaking change —
`SCHEMA_VERSION` must bump, and the operator must be given a path
from v1 to v2.

## Considered alternatives

### Merkle-tree / tree-hash of the log

Commit the whole log as a Merkle tree, re-root on each write, and
publish the root somewhere external (operator's keychain, git,
external witness).

**Rejected** because:

- Each write must either append a leaf and re-root (O(log N) on every
  entry — rework of the write path) or accept that intermediate
  roots are lost. The former is overkill for a single-user deployment;
  the latter provides no stronger guarantee than an HMAC chain.
- External publication of the root is the real tamper-evidence value
  of a Merkle tree, and that requires either an always-available
  remote witness or a human rhythm of committing roots — neither fits
  the single-user, offline-friendly deployment model.

### Detached signatures per entry (e.g. minisign, signify)

Sign each entry with a long-term key, write the signature into the
entry.

**Rejected** because:

- An attacker who deletes entry N cannot be detected by per-entry
  signatures — the remaining entries each still verify in isolation.
  Tamper-evidence requires a linkage between entries, which is
  exactly what the chain provides.
- Signature formats are heavier than a hex HMAC and require a more
  complex key lifecycle (pair, not symmetric) without adding anything
  the chain doesn't.

### Forward-secure MAC (e.g. evolving key per entry)

Derive a fresh MAC key per entry (HKDF-expand on the previous key);
the current key never retroactively verifies past entries so an
attacker who steals today's key cannot forge yesterday's history.

**Rejected for 1.0** because:

- The threat the chain addresses is *silent tampering by someone
  with log-write access*. If the attacker can also read the keyring
  (they usually cannot — different ACL), forward secrecy is
  marginally better, but the deployment profile is single-user and
  local; ACL separation is strong.
- Rotating the key off-disk per entry complicates the `verify-audit`
  command, which would need to walk the derivation chain from a
  stored root key.
- Can be retrofitted on top of the current chain without a second
  schema bump: the stored `chain_hmac` would remain; only the key
  used to compute it would evolve.

### Rewrite the v1 log into v2 on upgrade

Read every v1 entry, recompute a fake prev-HMAC chain over its
fields, emit a v2 log with `chain_hmac` populated.

**Rejected** because:

- Any bit-for-bit round-trip through JSON loses field-ordering
  subtleties. Copies archived off-host by operators for compliance
  would diverge from the upgraded on-host file — confusing, and
  damaging forensic provenance.
- The audit-chain key for the v1 history does not exist (it was
  minted on this upgrade); a "v2 chain" over v1 entries would be
  cryptographically meaningless and misleading.
- Renaming the v1 file preserves its exact bytes for forensics and
  is operationally obvious.

## Decision

1. **Per-entry chained HMAC-SHA256**, keyed on a new audit-chain
   key stored in the system keyring under `audit-chain-key`.
   Chain formula:
   `chain_hmac_n = HMAC-SHA256(k, chain_hmac_{n-1} || canonical(entry_n))`
   where `canonical(e)` is `json.dumps(e, sort_keys=True, separators=(",", ":"))` over the entry *without* the
   `chain_hmac` field, and `chain_hmac_0` is 32 zero bytes
   (genesis).
2. **Bump `SCHEMA_VERSION` from 1 to 2.** Every v2 entry carries a
   64-char lowercase-hex `chain_hmac` field. v1 entries never had
   one and never will.
3. **Rollover migration**. On `AuditLogger.__init__`, read the
   tail line of the existing log:
   - Empty or absent → start at genesis.
   - `schema_version == 2` with a valid `chain_hmac` → resume from
     that hmac.
   - Anything else (v1 tail, malformed line, wrong `schema_version`)
     → rename the file to `<path>.pre-chain-v2-<UTC timestamp>`,
     start a fresh chain at genesis in the original path, and
     write a stderr notice so the operator can locate the archived
     file. The archived file preserves exact bytes.
4. **`agent-auth verify-audit` CLI command.** Reads the audit-chain
   key from the keyring, replays the chain against the log file,
   exits 0 on success, 1 on a mismatch (with the failing line number
   on stderr), 2 on key or I/O failure. Legacy v1 entries are
   reported as `legacy_skipped` rather than counted as failures —
   they predate the chain and cannot be verified.
5. **Key management.** A new `AuditChainKey` `NewType` lives in
   `agent_auth.keys` next to `SigningKey` and `EncryptionKey`;
   `KeyManager.get_or_create_audit_chain_key` reads or generates
   32 random bytes from `os.urandom`. The signing key is *not*
   reused — a future compromise of one keyring entry should not
   pivot into tampered-but-valid-looking audit chains.

## Consequences

**Positive**:

- Closes AU-9. A local attacker with log-write access cannot
  silently edit or delete entries — the chain breaks at the first
  tampered entry and at every subsequent entry, detectable by any
  operator who runs `agent-auth verify-audit`.
- The keyring ACL forms a second trust boundary around the chain
  key: a compromise of the log file alone is not enough to mint a
  valid chain, and on macOS / libsecret the keyring grants are
  per-program-path so an attacker also needs to execute as the
  agent-auth binary.
- `verify-audit` is a single-command integrity check operators can
  run on any schedule, including in automated posture checks.
- Forensics-preserving rollover: the exact bytes of the v1 log are
  retained on disk in the archived file.

**Negative / accepted trade-offs**:

- `SCHEMA_VERSION` breaking bump. The contract-tests file pins
  v1 → v2 and fails loudly on any accidental regression. Documented
  in `design/DESIGN.md` §Audit log fields.
- Tampering with the *archived* `pre-chain-v2-*` file is still
  undetectable — the v1 format had no MAC. That is unchanged from
  today and out of scope for this ADR.
- The chain verifies a sequence, not wall-clock time. An attacker
  who replays *the whole log* onto another machine will verify
  successfully (the chain doesn't bind to file path or host). That
  is an acceptable trade; hostname binding would add operational
  friction for the one-machine deployment.
- `AuditLogger` loading the log's tail on startup is O(file size).
  Audit logs are rotated via `logrotate` per DESIGN.md; this cost
  has not shown up in the performance budget.

## Follow-ups

- Consider forward-secure derivation if the threat model expands
  to include a local attacker with keyring access.
- `verify-audit --since <timestamp>` could let operators verify
  only the recent chain on a large rotated file. Not shipped for
  1.0.
- External witness (publish a daily root to an operator-controlled
  git repo) remains a future option and is compatible with this
  chain — the root would simply be the latest `chain_hmac`.
