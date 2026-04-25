<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# gpg-bridge

Host-side HTTP bridge that performs git's commit / tag signing on
behalf of devcontainer-resident callers. Mirrors the things-bridge
split: the bridge holds no GPG logic itself — it shells out to a
configured backend (default
[`gpg-backend-cli-host`](../gpg-backend-cli-host/), which calls the
real host `gpg`). Authorization is delegated to
[`agent-auth`](../agent-auth/) under the `gpg:sign` scope, and key
allowlisting sits in bridge config.

## Public surface

### CLI — `gpg-bridge`

| Subcommand         | Purpose                                           |
| ------------------ | ------------------------------------------------- |
| `gpg-bridge serve` | Start the HTTP server (default `127.0.0.1:9300`). |

### HTTP

POST `/gpg-bridge/v1/sign` and `/gpg-bridge/v1/verify`, each
forwarding to the configured backend after `agent-auth` authorization
and per-key allowlist enforcement. Health and metrics on
`/gpg-bridge/health` / `/gpg-bridge/metrics`.

## Configuration

`~/.config/gpg-bridge/config.yaml` controls host/port, the
`agent-auth` URL, the `gpg_backend_command` argv, and the
`allowed_signing_keys` list. TLS material can be supplied so a
devcontainer reaching the host bridge gets transport protection.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-bridge/install.sh | bash
```

Or run from a development checkout via `task gpg-bridge -- <args...>`.

## Related design

- ADR [0033 — gpg-bridge / gpg-cli split](../../design/decisions/0033-gpg-bridge-cli-split.md)
