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

`needs-info` and `blocked` look similar but apply at different stages: `needs-info` means the issue is awaiting clarification from an external reporter *before* triage is complete (no Claude Code session has picked it up), while `blocked` means a Claude Code session is mid-execution and has parked the issue awaiting an answer it captured as a `Claude: Blocked — <question>` comment. If both states ever apply, the execution-state `blocked` is the active one — drop the `needs-info` label when an agent picks up the issue.
