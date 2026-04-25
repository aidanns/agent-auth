<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0042 — Bridge-owned signing-key passphrase store in the system keyring

## Status

Accepted — 2026-04-25.

## Context

`gpg-bridge` shells the host `gpg` binary with
`--batch --no-tty --pinentry-mode loopback` and provides **no**
passphrase source
(`packages/gpg-bridge/src/gpg_bridge/gpg_client.py`,
post-#316 / PR #334 collapse). That leaves only two states in which
a request can succeed:

1. The signing key carries no passphrase. The on-disk secret-key
   file is then the sole barrier between an attacker with file
   access and a forged signature — weaker than the project's other
   key-material postures.
2. The host `gpg-agent` already has the passphrase cached from a
   prior interactive use. Cache TTL expiry, agent restart, host
   reboot, or sleep / wake all evict it; the next signing request
   then hangs against a non-existent pinentry until the bridge's
   per-subprocess deadline fires (issue #331 / PR #339, now mapped
   to `signing_backend_unavailable`).

Both states force the operator to choose between weakening the
key's at-rest posture and accepting a wedge-and-hang failure mode
that recurs after every cache eviction. The bridge is the obvious
place to break the tradeoff: it already has a per-fingerprint
allowlist (`Config.allowed_signing_keys`), already runs as the
same user as `gpg-agent`, and already gates every signing request
behind agent-auth. Adding bridge-owned passphrase material raises
the bar from "anyone with the secret-key file" to "anyone with
the secret-key file *and* the keyring", which is the same bar the
project already applies to the agent-auth signing key
([ADR 0008](0008-system-keyring-for-key-material.md)). The threat
model and the answer are identical: 32 bytes of symmetric secret
material belong in the OS keyring, not on disk.

The companion `things-cli` already wraps the `keyring` library in
`KeyringStore` (`packages/things-cli/src/things_cli/credentials.py`).
The shape — `service` / `username` lookup keyed by a stable string,
backend-error wrapping, idempotent `clear` — transfers directly to
the bridge side, with `service = "gpg-bridge"` and `username` =
the signing-key fingerprint.

This ADR builds on
[ADR 0033](0033-gpg-bridge-cli-split.md) (the gpg-bridge / gpg-cli
trust boundary): the passphrase moves *across* that boundary in
exactly one place — from the bridge's keyring read into the host
`gpg` subprocess via `--passphrase-fd`. It does not move into the
container, the HTTP API, the audit log, or the bridge's stdout /
stderr / response bodies.

## Considered alternatives

### Bind-mount `gpg-agent` socket into the devcontainer (status quo of the rejected alternative in ADR 0033)

Already rejected for `gpg-bridge` itself by ADR 0033. The
passphrase variant — let `gpg-agent` keep the passphrase, expose
its socket — has the same flaws (full-IPC-surface exposure, no
per-key scoping, no audit). Mentioned only to note that the
"why not just use gpg-agent?" question was already answered upstream.

### Cache the passphrase inside `gpg-bridge`'s in-memory state

Hold the passphrase in a Python dict on the `GpgBridgeServer`
instance after the operator runs an interactive `passphrase set`
command, evict on configurable TTL.

**Rejected** because:

- Passphrase survives only until process restart. Every
  `task gpg-bridge -- serve` reboot (e.g. after a config edit, a
  package upgrade, the host machine waking from sleep) demands a
  re-prime. Same operational cost as the gpg-agent case it tries
  to escape.
- Adds a soft-state cache that participates in the bridge's
  resilience story (graceful shutdown, restart, crash) without
  earning anything the keyring doesn't already give.
- A swap or core-dump can spill an in-memory dict to disk on a
  long-running host. The keyring backends (Keychain, libsecret)
  already handle the at-rest problem with OS-level mlock /
  encryption.

### Encrypt-on-disk file under `$XDG_DATA_HOME/gpg-bridge/`

Mirror ADR 0008's *rejected* "keys in a config file at a different
path" alternative, but with the file stored encrypted at rest.

**Rejected** for the same reasons ADR 0008 rejected its file
analogue: path separation defeats co-location, not exfiltration;
agent-auth ends up owning key-file lifecycle (atomic writes,
permissions, backup opt-out) when the OS keyring already does that
for free; and the resulting custom encryption-at-rest scheme has
to choose its own KDF / ciphertext format, becoming a second
not-quite-keyring abstraction inside the codebase.

### Per-key scopes (`gpg:sign:<fingerprint>`) instead of an allowlist + passphrase store

Defer the passphrase question entirely; lean harder on
agent-auth-side authorization with per-fingerprint scopes.

**Rejected** because the passphrase question is orthogonal to the
authz question — even with an exact-fingerprint scope, the bridge
still has to drive the host `gpg` and the host `gpg` still asks
for a passphrase. ADR 0033 already explains why per-fingerprint
scopes are not the right shape for the token surface; revisiting
that here would be scope creep.

## Decision

Add a bridge-owned, keyring-backed passphrase store keyed by
signing-key fingerprint, surfaced through three new
`gpg-bridge passphrase` subcommands and consumed transparently by
the existing sign path.

### Persistence shape

`packages/gpg-bridge/src/gpg_bridge/passphrase_store.py`:

- `KeyringPassphraseStore.set(fingerprint: str, passphrase: str)`
- `KeyringPassphraseStore.get(fingerprint: str) -> str | None`
- `KeyringPassphraseStore.delete(fingerprint: str) -> None` (idempotent)
- `KeyringPassphraseStore.list_fingerprints() -> list[str]`

Backed by `keyring.set_password / get_password / delete_password`
with `service = "gpg-bridge"` and `username = <FP-uppercase-no-0x>`.
Keyring backend errors wrap as `PassphraseStoreError`; "no such
entry" reads return `None` (not an exception, the caller checks
nullity per request). One entry per key.

### CLI surface

```
gpg-bridge passphrase set    <fingerprint>   # prompts no-echo
gpg-bridge passphrase clear  <fingerprint>   # idempotent
gpg-bridge passphrase list                   # fingerprints only
```

`set` rejects fingerprints not in `Config.allowed_signing_keys`
with a directed message, and rejects fingerprints `gpg --list-secret-keys <FP>` cannot resolve on the host. Passphrase
input is read via `getpass.getpass` so it never echoes and never
appears in shell history. `list` reads from the keyring (not from
the allowlist) — it answers "what is stored", which is a strict
subset of the allowlist and is the operationally useful question.
Passphrases never appear in any output; only fingerprints do.

### Bridge wiring

`Config.passphrase_store_enabled: bool = True` — operators who
prefer to keep relying on `gpg-agent` set this to `False`, and
the sign path reverts to today's behaviour (no `--passphrase-fd`
in argv, no keyring read). The flag is **enabled by default**:
the keyring is empty on first boot, so a no-op default still
matches today's keyless / agent-cached path.

`GpgSubprocessClient.sign` is extended to consult the store after
the existing allowlist check. When a passphrase is found:

1. `read_fd, write_fd = os.pipe()`.
2. `subprocess.Popen(argv + ["--passphrase-fd", str(read_fd)], pass_fds=(read_fd,), ...)`.
3. Parent immediately closes `read_fd` (the child inherited it).
4. Parent writes `passphrase + "\n"` to `write_fd` and closes
   `write_fd`.
5. Parent writes the payload to stdin and reads stdout / stderr
   per the existing contract.
6. All fds are closed inside a `try / finally` so a payload write
   failure or a `Popen` failure does not leak descriptors.

When no passphrase is found for the requested fingerprint, the
existing `subprocess.run`-based path runs unchanged. Verify is
unchanged in either case — `gpg --verify` does not need a
passphrase.

### Wrong-passphrase mapping

A wrong passphrase makes host `gpg` exit non-zero with
`gpg: signing failed: Bad passphrase` on stderr. The existing
`_raise_for_stderr` classifier in
`gpg_bridge.gpg_client` is extended to recognise that string and
raise `GpgBackendUnavailableError`, which the server already maps
to HTTP 503 `signing_backend_unavailable` (issue #331 / PR #339).
Reusing that code keeps the wire surface narrow — the public
discriminant `gpg-cli` already handles is sufficient — and avoids
introducing a new error code with no concrete consumer. If a
future caller needs to distinguish wrong-passphrase from
host-agent-wedge, a new code can be added with a structured
`detail` carve-out.

### Trust-boundary delta

The bridge process now holds **unlocked passphrase material in
memory** for the duration of one signing request: from the
`keyring.get_password` call to the `os.close(write_fd)` after the
child has read it. This is a real change to the bridge's threat
posture compared to ADR 0033's original shape:

- The Python-process memory image briefly contains an unlocked
  signing-key passphrase. Compromise of the bridge process during
  that window (debugger attach, ptrace, core dump) leaks the
  passphrase. Defence: the bridge runs as the operator's
  unprivileged user; same-user same-host code execution is
  already inside the threat boundary
  ([ADR 0008](0008-system-keyring-for-key-material.md)), and
  ptrace-attach for that uid implies the attacker can also read
  the keyring directly via `keyring.get_password`.
- The passphrase is never logged, never appears in HTTP
  responses, never crosses into the devcontainer, and never
  appears in stdout / stderr. The bridge's stderr scrubbing
  (`packages/gpg-bridge/src/gpg_bridge/server.py`) treats the
  passphrase as never-emitted-in-the-first-place rather than
  redacted-after-the-fact: the only file descriptor it touches
  is the write end of the `--passphrase-fd` pipe.
- Tests assert (a) no passphrase string in any captured output,
  (b) no extra fds leak across two consecutive sign requests, and
  (c) the bridge's existing log path emits nothing new on a
  passphrase-enabled sign.

The audit log is unchanged. Per
[ADR 0024](0024-audit-log-shared-envelope.md) /
[ADR 0028](0028-audit-log-hmac-chain.md), audit entries already
hash the payload and record the resolved fingerprint; the
passphrase is not a property of the request that needs to be
recorded.

## Consequences

- **First-time setup ergonomics improve.** A devcontainer-authored
  signed commit no longer requires the operator to prime
  `gpg-agent` interactively before each session. One-time
  `gpg-bridge passphrase set <FP>` per key persists across
  bridge / agent / host restarts.
- **Wedge case becomes much rarer** (companion of issue #331). The
  hang-and-fail-fast path stays in place for the case where the
  operator has not stored a passphrase, and the directed
  `signing_backend_unavailable` message still names the most likely
  cause.
- **Operators with a stricter posture can opt out.** Setting
  `passphrase_store_enabled: false` in `config.yaml` reverts to
  today's behaviour with one config-line.
- **Migration cost is zero for existing operators.** The keyring
  is empty on first boot of the new bridge; the sign path detects
  no stored passphrase and runs the existing argv. Operators who
  do nothing keep getting today's behaviour.
- **`keyring>=25.0` becomes a `gpg-bridge` runtime dependency**
  (already present in `things-cli`). The workspace dep-graph
  allowlist (ADR 0036) is unchanged — `keyring` is third-party,
  not workspace-internal.
- **Trust boundary widens by one process-memory window per sign.**
  Captured in the trust-boundary-delta section above; mitigated
  by reusing the keyring-read posture of ADR 0008 and keeping
  every other surface the same.
- **Follow-ups deferred:** automatic passphrase rotation (operator
  rotates via `clear` + `set` for now); cross-host sync (each host
  owns its own keyring entries); a per-fingerprint scope split if
  a future deployment shape needs it.

## Follow-ups

- GitHub issue: an operator-facing rotation policy if a concrete
  use case asks for one. Defer until measured need.
- GitHub issue: cross-host passphrase sync if multi-host bridges
  ever ship.
