<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# things-bridge

HTTP bridge that exposes a read-only, agent-auth-protected view of
the Things 3 to-do app. Holds no Things logic itself: each request is
translated into a subprocess invocation of a configured Things-client
CLI (default [`things-client-cli-applescript`](../things-client-cli-applescript/),
which shells out to `osascript` on macOS) and the JSON envelope on
stdout is parsed and returned to the caller.

## Public surface

### CLI — `things-bridge`

| Subcommand            | Purpose                                           |
| --------------------- | ------------------------------------------------- |
| `things-bridge serve` | Start the HTTP server (default `127.0.0.1:9200`). |

### HTTP — `/things-bridge/v1/*`

Read-only endpoints over Things `todos`, `projects`, `areas`. The full
contract lives in [`openapi/things-bridge.v1.yaml`](./openapi/things-bridge.v1.yaml).
`/things-bridge/health` and `/things-bridge/metrics` are unversioned.

## Configuration

`~/.config/things-bridge/config.yaml` configures host/port, the
`agent-auth` URL, and the `things_client_command` argv used to launch
the Things-client subprocess. For Linux devcontainer e2e, point the
command at the test-only fake:

```yaml
things_client_command:
  - python
  - -m
  - tests.things_client_fake
  - --fixtures
  - tests/things_client_fake/fake-things.yaml
```

The bridge re-validates every request with `agent-auth` before
acting; it never caches authorisation decisions and never trusts the
bearer token it receives directly.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-bridge/install.sh | bash
```

Or run from a development checkout via `task things-bridge -- <args...>`.

## Related design

- ADR [0001 — Things-client fake](../../design/decisions/0001-things-client-fake.md) (superseded by 0003)
- ADR [0003 — Things-client CLI split](../../design/decisions/0003-things-client-cli-split.md)
- ADR [0013 — AppleScript Things bridge](../../design/decisions/0013-applescript-things-bridge.md)
