<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Host-side gpg-bridge setup and troubleshooting

This page is for operators wiring the host's `gpg-bridge` to a
devcontainer's `gpg-cli`. The architecture is described in
[ADR 0033](../../design/decisions/0033-gpg-bridge-cli-split.md) and
the wiring procedure in CONTRIBUTING.md §
"Signed commits inside the devcontainer". This page focuses on the
specific failure modes that
`scripts/setup-devcontainer-signing.sh`'s smoke test surfaces, and
how to remediate each on the host side.

## Smoke-test failure-mode catalogue

The setup script's smoke test runs four probes. Failures here map
back to the script's named failure messages (issue #333).

### Probe 3: bridge unreachable

Symptom — the script prints:

```
setup-devcontainer-signing: probe failed: bridge unreachable at <URL>.
```

Causes, in rough decreasing order of likelihood:

1. **Bridge not running on the host.** Start it with
   `task gpg-bridge -- serve`. Confirm it bound a port with
   `lsof -i -P -n | grep gpg-bridge` or by looking at the bridge's
   stdout/stderr.
2. **Wrong URL from the devcontainer's perspective.** Docker
   Desktop and most container runtimes route the host as
   `host.docker.internal`. `127.0.0.1` resolves to the
   container's own loopback, where nothing is listening. Use
   `host.docker.internal` (or whatever the runtime documents) in
   `--bridge-url`.
3. **Bridge bound to a host-only interface.** If the bridge is
   serving on `127.0.0.1` (the default) but the container reaches
   it via a Docker bridge network, the connection is refused. Set
   the bridge's `bind_host` config to `0.0.0.0` (or to the
   docker-network gateway interface) and restart it.
4. **TLS handshake failure (`HTTP 000` from curl).** The bridge
   serves https; if the container can't validate the cert, the
   request never completes. Pass `--ca-cert-path <PATH>` to the
   setup script with the CA that signed the bridge cert, or — for
   self-signed dev certs — copy the cert into the container's
   trust store and rebuild.

### Probe 4: trial sign — `unauthorized` (gpg-cli exit 3)

Symptom — the script prints:

```
setup-devcontainer-signing: probe failed: bridge rejected the token (unauthorized).
setup-devcontainer-signing: mint a new one on the host with 'task agent-auth -- token create --scope gpg:sign=allow --json'.
```

The token is valid HTTP-wise (the bridge accepted the request) but
agent-auth rejected it. Common causes:

- **Token expired or revoked.** Mint a fresh one on the host:
  `task agent-auth -- token create --scope gpg:sign=allow --json`,
  copy the `access_token` value into a re-run of the setup script.
- **Token format corrupted in transit.** A misplaced newline or
  extra whitespace can break the HMAC. Re-paste from the JSON
  output.

### Probe 4: trial sign — `forbidden` (gpg-cli exit 4)

Symptom — the script prints:

```
setup-devcontainer-signing: probe failed: bridge accepted the token but denied the request (forbidden).
setup-devcontainer-signing: causes: token lacks gpg:sign=allow, or signing key <FP> is not in the bridge's allowed_signing_keys list.
```

Two distinct causes:

- **Token lacks `gpg:sign=allow`.** The token's scopes were
  scoped narrower at mint time, e.g. `gpg:sign=prompt` (which
  requires JIT approval, not in scope for an automated devcontainer
  flow). Re-mint with `--scope gpg:sign=allow`.
- **Signing key not in `allowed_signing_keys`.** The bridge
  enforces a per-key allowlist *before* asking agent-auth. Edit
  the bridge's `config.yaml` `allowed_signing_keys` list to
  include the fingerprint, then restart the bridge. The
  fingerprint must match the form gpg uses (typically the long
  fingerprint, no spaces).

### Probe 4: trial sign — `signing backend unavailable` (gpg-cli exit 5)

Symptom — `gpg-cli` exits with a stderr line of the form:

```
gpg-cli: signing backend unavailable: host gpg-agent likely needs
allow-loopback-pinentry and a primed passphrase cache; see
docs/operations/gpg-bridge-host-setup.md
```

The bridge surfaced a 503 with `error: "signing_backend_unavailable"`
because the host `gpg` subprocess hung past the bridge's per-request
deadline (default 10s). The bridge itself is reachable; the wedge
is at the gpg layer. Causes:

- **Host gpg-agent is prompting for a passphrase that nothing can
  answer.** The bridge runs as a background service, so an
  interactive pinentry has no terminal to draw on. Add
  `allow-loopback-pinentry` to `~/.gnupg/gpg-agent.conf` and
  restart the agent (`gpgconf --kill gpg-agent`). The bridge uses
  `--pinentry-mode loopback` to feed the passphrase through the
  agent socket.
- **Passphrase not cached.** Even with `allow-loopback-pinentry`,
  the agent needs to know the passphrase. Either pre-warm the
  cache (sign a dummy payload manually before starting the
  bridge: `echo | gpg --clearsign > /dev/null`), move the key
  to a passphrase-less subkey reserved for signing, or — the
  recommended path per
  [ADR 0042](../../design/decisions/0042-gpg-bridge-passphrase-store.md)
  — store the passphrase in the bridge's keyring once with
  `task gpg-bridge -- passphrase set <FP>`. The bridge then
  feeds it to `gpg` via `--passphrase-fd` on every sign request,
  removing the dependency on `gpg-agent`'s cache.
- **Host `gpg` binary missing.** `command -v gpg` on the host
  must succeed and resolve to a 2.x binary. Install via
  `brew install gnupg` on macOS or `apt-get install gnupg2` on
  Debian/Ubuntu.

### Probe 4: trial sign — `bridge unavailable` (gpg-cli exit 5)

Symptom — `gpg-cli` exits with `bridge unavailable: <detail>` on
stderr (rather than `signing backend unavailable`). This is the
generic 5xx / network path: the bridge process itself is the
problem, not the gpg subprocess behind it. Distinguish from the
`signing backend unavailable` case above, which is the wedge case
with a directed remediation (`allow-loopback-pinentry`).

Common causes: bridge crashed mid-request, an upstream proxy is
returning 5xx, or the bridge's authz delegation to `agent-auth`
itself failed (502 `authz_unavailable`). Check `gpg-bridge`'s log
to disambiguate.

## Verifying the host bridge in isolation

If a smoke-test failure isn't obviously a config problem, check
the bridge's behaviour without the devcontainer in the loop. From
the host:

```bash
# Health probe — should return 200 with a {"status":"ok"} body
# (requires a token with the gpg-bridge:health scope).
curl -fsS \
  -H "Authorization: Bearer $(task agent-auth -- token create --scope gpg-bridge:health=allow --json | jq -r .access_token)" \
  https://127.0.0.1:8443/gpg-bridge/health

# Trial sign — same payload the smoke test uses.
echo 'host-side smoke test' | gpg -bsau <FP>
```

If the trial sign hangs from the host as well, the issue is on
the host side (gpg / gpg-agent / passphrase) and the devcontainer
wiring is fine. If it succeeds on the host but fails through the
devcontainer, the issue is in the bridge wiring or in the agent's
loopback-pinentry config.
