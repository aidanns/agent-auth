<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# things-cli

Read-only command-line client for [`things-bridge`](../things-bridge/).
Auto-refreshes / reissues tokens via [`agent-auth`](../agent-auth/) and
emits human-readable text by default (or JSON with `--json`).

## Public surface

### CLI — `things-cli`

| Subcommand                        | Purpose                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------ |
| `things-cli login`                | Interactively store credentials (bridge URL, auth URL, family id, refresh token).    |
| `things-cli status`               | Show redacted credential status.                                                     |
| `things-cli logout`               | Discard stored credentials.                                                          |
| `things-cli todos list / show`    | List/show todos (filter by status, list, project, area; `--list TMTodayListSource`). |
| `things-cli projects list / show` | List/show projects.                                                                  |
| `things-cli areas list / show`    | List/show areas.                                                                     |

## Credentials

Stored in the system keyring by default. When no keyring backend is
available (e.g. inside a devcontainer), the CLI falls back to a
`0600` YAML file at `~/.config/things-cli/credentials.yaml`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-cli/install.sh | bash
```

Or run from a development checkout via `task things-cli -- <args...>`.

## Related design

- ADR [0003 — Things-client CLI split](../../design/decisions/0003-things-client-cli-split.md)
- ADR [0030 — Per-service HTTP client libraries](../../design/decisions/0030-per-service-http-client-libraries.md)
