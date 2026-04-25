<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# things-client-cli-applescript

macOS-only AppleScript-backed implementation of the Things-client
contract (defined under
[`agent_auth_common.things_client_common`](../agent-auth-common/)).
Invoked as a subprocess by [`things-bridge`](../things-bridge/), but
also useful standalone for local Things 3 debugging without the
bridge or `agent-auth`.

## Public surface

### CLI — `things-client-cli-applescript`

Read-only commands over the Things 3 model; all emit a JSON envelope
on stdout suitable for the `things-bridge` subprocess parser.

| Subcommand      | Purpose                                               |
| --------------- | ----------------------------------------------------- |
| `todos list`    | List todos (optional status / list / project / area). |
| `todos show`    | Show a single todo by id.                             |
| `projects list` | List projects.                                        |
| `projects show` | Show a single project by id.                          |
| `areas list`    | List areas.                                           |
| `areas show`    | Show a single area by id.                             |

## Platform requirements

- macOS with Things 3 installed.
- Automation permission for the invoking process to control Things 3.

The package installs on Linux (some contract-test scenarios need
that), but every command will fail at runtime without `osascript`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-client-cli-applescript/install.sh | bash
```

Or run from a development checkout via
`task things-client-applescript -- <args...>`.

## Related design

- ADR [0013 — AppleScript Things bridge](../../design/decisions/0013-applescript-things-bridge.md)
- ADR [0003 — Things-client CLI split](../../design/decisions/0003-things-client-cli-split.md)
