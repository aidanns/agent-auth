<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# agent-auth-common

Library-only workspace package shared by every service in this repo.
Stdlib-only at runtime so it stays cheap to consume from CLIs that
only need typed clients or domain models.

## Public surface

| Module                             | Purpose                                                                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_auth_client`                | Typed HTTP client for the `agent-auth` server (token validate / refresh / management endpoints).                                                |
| `things_bridge_client`             | Typed HTTP client for the `things-bridge` HTTP API.                                                                                             |
| `things_models`                    | Dataclasses + typed `NewType` ids (`TodoId`, `ProjectId`, `AreaId`) shared by every Things-side consumer.                                       |
| `things_client_common`             | Shared argparse / dispatch surface implemented by every Things-client CLI (production AppleScript and the test fake).                           |
| `gpg_models`                       | Request / result dataclasses and `GpgError` hierarchy shared by `gpg-bridge` and `gpg-cli`.                                                     |
| `server_metrics`                   | Prometheus exposition-format helper used by the HTTP servers (`agent-auth`, `things-bridge`, `gpg-bridge`).                                     |
| `tests_support` (extra, test-only) | Out-of-process notifier sidecar consumed by Docker integration tests; gated behind the `tests` extra so it never ships in a production install. |

## Install

This package is a workspace dependency — installing any of the
service packages (`agent-auth`, `things-bridge`, `gpg-bridge`, ...) pulls
it in transitively. There is no standalone install path or CLI.

## Related design

- ADR [0030 — Per-service HTTP client libraries](../../design/decisions/0030-per-service-http-client-libraries.md)
- ADR [0003 — Things-client CLI split](../../design/decisions/0003-things-client-cli-split.md)
