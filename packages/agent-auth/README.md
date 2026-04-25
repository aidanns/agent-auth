<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# agent-auth

Token-based authorization service for gating AI-agent access to local
applications. Issues HMAC-signed access / refresh token pairs scoped
under a three-tier model (`allow` / `prompt` / `deny`), persists them
in an encrypted SQLite store, and exposes the trust-root HTTP API that
every other service in this repo validates against.

## Public surface

### CLI — `agent-auth`

| Subcommand                         | Purpose                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `agent-auth serve`                 | Start the HTTP server (default `127.0.0.1:9100`).                          |
| `agent-auth token create`          | Mint a new token family with a scope set.                                  |
| `agent-auth token list`            | List token families.                                                       |
| `agent-auth token modify`          | Update scopes / expiry on an existing family.                              |
| `agent-auth token rotate`          | Rotate the access / refresh pair for a family.                             |
| `agent-auth token revoke`          | Revoke an entire family (refresh-token reuse triggers this automatically). |
| `agent-auth management-token show` | Print the bootstrap management token used to authenticate other CLI calls. |

The `agent-auth-notifier` sidecar lives in this package too — an
out-of-process JIT approval prompt for `prompt`-tier scopes.

### HTTP — `/agent-auth/v1/*`

Validate, refresh, and management endpoints documented in
[`openapi/agent-auth.v1.yaml`](./openapi/agent-auth.v1.yaml). The
unversioned `/agent-auth/health` and `/agent-auth/metrics` endpoints
are also served.

## Configuration

`~/.config/agent-auth/config.yaml` controls host/port, token TTLs,
notification plugin URL, and TLS material. The XDG layout for the
SQLite store and audit log is documented in
[ADR 0012](../../design/decisions/0012-xdg-path-layout.md).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/agent-auth/install.sh | bash
```

Or run from a development checkout via `task agent-auth -- <args...>`.

## Related design

- ADR [0006 — Token format](../../design/decisions/0006-token-format.md)
- ADR [0007 — SQLite field-level encryption](../../design/decisions/0007-sqlite-field-level-encryption.md)
- ADR [0008 — System keyring for key material](../../design/decisions/0008-system-keyring-for-key-material.md)
- ADR [0009 — CLI / server split](../../design/decisions/0009-cli-server-split.md)
- ADR [0010 — Three-tier scope model](../../design/decisions/0010-three-tier-scope-model.md)
- ADR [0011 — Refresh-token reuse, family revocation](../../design/decisions/0011-refresh-token-reuse-family-revocation.md)
