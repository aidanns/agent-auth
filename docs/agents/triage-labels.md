<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Triage Labels

The skills speak in terms of five canonical triage labels. This repo uses the canonical names verbatim:

- `needs-triage` — maintainer needs to evaluate this issue
- `needs-info` — waiting on reporter for more information
- `ready-for-agent` — fully specified, ready for an AFK agent
- `ready-for-human` — requires human implementation
- `wontfix` — will not be actioned

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the matching label string above.

`wontfix` already exists in this repo. The other four are created on first use via `gh label create <name>`.

These labels describe **triage state**. They are orthogonal to the existing **execution-state** labels (`scheduled`, `in-progress`, `paused`, `blocked`, `needs fix`) — those track an active Claude Code session's progress and can coexist on the same issue.
