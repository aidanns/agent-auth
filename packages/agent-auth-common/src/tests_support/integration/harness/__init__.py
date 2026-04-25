# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fluent Docker Compose harness for the integration test suite.

Each per-service ``conftest.py`` builds a :class:`DockerComposeCluster`
per test, starts it, reads ports off :class:`DockerPort` accessors, and
tears it down on fixture teardown — with optional log capture into the
pytest ``tmp_path`` when a test fails.

The harness wraps ``docker compose`` directly (subprocess, no
``testcontainers-python``), so every action maps 1:1 to a CLI invocation
a developer can reproduce locally. It explicitly never mutates
``os.environ`` — configured env vars flow into the ``docker compose``
subprocess via ``env=``, and the project name is passed on the CLI via
``--project-name``.

Inspired by ``palantir/docker-compose-rule`` (JUnit rule). See
``design/decisions/0005-integration-harness-rework.md`` for the rework
rationale.
"""

from tests_support.integration.harness._cluster import (
    ClusterStartupTimeout,
    DockerComposeCluster,
    DockerComposeClusterBuilder,
    ServiceHandle,
    StartedCluster,
)
from tests_support.integration.harness._port import DockerPort
from tests_support.integration.harness._wait import (
    HealthChecks,
    ServiceWaitFn,
)

__all__ = [
    "ClusterStartupTimeout",
    "DockerComposeCluster",
    "DockerComposeClusterBuilder",
    "DockerPort",
    "HealthChecks",
    "ServiceHandle",
    "ServiceWaitFn",
    "StartedCluster",
]
