<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# docker/

Shared integration-test infrastructure. These assets span more than one
service and are deliberately kept at the repo root rather than under a
single `packages/<svc>/docker/` directory.

| File                                        | Purpose                                                                                                    |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `docker-compose.yaml`                       | One compose file launches the full `agent-auth` + `things-bridge` + `things-cli` + fake-AppleScript stack. |
| `Dockerfile.agent-auth.test`                | Image for the `agent-auth` container.                                                                      |
| `Dockerfile.things-bridge.test`             | Image for the `things-bridge` container.                                                                   |
| `Dockerfile.things-cli.test`                | Image for the `things-cli` container.                                                                      |
| `Dockerfile.things-client-applescript.test` | Image for the AppleScript-fake container used in Linux CI.                                                 |
| `config.test.yaml`                          | Shared test config mounted into the `agent-auth` container.                                                |

`tests/integration/` drives the compose file via the `DockerComposeCluster`
builder — see `tests/test_harness_cluster/` for the Python API and
`tests/integration/conftest.py` for the per-service fixtures.
