<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# gpg-bridge

Host-side HTTP bridge that performs git's commit / tag signing on
behalf of devcontainer-resident callers. The bridge owns the
`gpg`-argv construction directly (per the
[ADR 0033 collapse-the-backend-hop amendment](../../design/decisions/0033-gpg-bridge-cli-split.md)
of 2026-04-25), shelling out to the configured `gpg_command`
(default `gpg`) per request. Authorization is delegated to
[`agent-auth`](../agent-auth/) under the `gpg:sign` scope, and key
allowlisting sits in bridge config.

## Public surface

### CLI — `gpg-bridge`

| Subcommand         | Purpose                                           |
| ------------------ | ------------------------------------------------- |
| `gpg-bridge serve` | Start the HTTP server (default `127.0.0.1:9300`). |

### HTTP

POST `/gpg-bridge/v1/sign` and `/gpg-bridge/v1/verify`, each
invoking the configured `gpg` after `agent-auth` authorization and
per-key allowlist enforcement. Health and metrics on
`/gpg-bridge/health` / `/gpg-bridge/metrics`.

## Configuration

`~/.config/gpg-bridge/config.yaml` controls host/port, the
`agent-auth` URL, the `gpg_command` argv (default `["gpg"]`), and
the `allowed_signing_keys` list. TLS material can be supplied so a
devcontainer reaching the host bridge gets transport protection.

> Migration note (2026-04, issue
> [#316](https://github.com/aidanns/agent-auth/issues/316)): the
> `gpg_backend_command` config key is renamed to `gpg_command`, and
> its default is now `["gpg"]` rather than
> `["gpg-backend-cli-host"]`. Operators with a hand-edited config
> file should rename the key on upgrade; the value can be left
> unchanged if it already pointed at a `gpg` binary, or shortened
> to the new default if it pointed at the deleted
> `gpg-backend-cli-host`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-bridge/install.sh | bash
```

Or run from a development checkout via `task gpg-bridge -- <args...>`.

## Related design

- ADR [0033 — gpg-bridge / gpg-cli split](../../design/decisions/0033-gpg-bridge-cli-split.md)
