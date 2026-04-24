# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Docker-backed fixtures for things-bridge integration tests.

Each test gets its own multi-service Compose project (an ``agent-auth``
service for token validation plus a ``things-bridge`` service for the
HTTP surface under test). The bridge invokes the in-tree fake Things
client subprocess, fed by a YAML fixture the per-test fixture writes
into a bind-mounted directory.

Tests address the bridge through its host-mapped loopback port; the
``agent-auth`` service is reached only via the in-container ``agent-auth``
CLI (used here to mint scoped tokens).

Stack pinning: the topology lives in ``docker/docker-compose.yaml`` (the
shared compose file used by every per-service fixture in this tree).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration._support import (
    COMPOSE_FILE,
    phase_timer,
    seed_empty_fixtures_dir,
)
from tests.integration.conftest import (
    AGENT_AUTH_INTERNAL_PORT,
    APPROVAL_PLUGINS,
    BASELINE_CONFIG,
    AgentAuthContainer,
    _compose_image_env,
    _test_failed,
)
from tests.integration.harness import (
    DockerComposeCluster,
    HealthChecks,
    StartedCluster,
)
from things_bridge_client import ThingsBridgeClient

THINGS_BRIDGE_INTERNAL_PORT = 9200


@dataclass
class ThingsBridgeStack:
    """Handle for a running ``agent-auth`` + ``things-bridge`` Compose pair.

    The stack is exposed to tests through the bridge's host-mapped
    loopback port. ``agent_auth`` is the in-container handle used to
    mint and revoke tokens. ``cluster`` exposes the harness-level
    compose controls (``exec``, ``stop_service``) so callers that need
    cross-service behaviour — e.g. stopping ``agent-auth`` mid-test —
    don't have to reach for ``subprocess.run`` directly.
    """

    base_url: str
    cluster: StartedCluster
    agent_auth: AgentAuthContainer
    fixtures_dir: Path

    def client(self) -> ThingsBridgeClient:
        """Return a :class:`ThingsBridgeClient` bound to this stack's bridge URL."""
        return ThingsBridgeClient(self.base_url, timeout_seconds=10.0)

    def write_fixture(self, fixture: dict[str, Any]) -> None:
        """Write/replace ``things.yaml`` in the bind-mounted fixtures dir."""
        path = self.fixtures_dir / "things.yaml"
        path.write_text(yaml.safe_dump(fixture))
        os.chmod(path, 0o644)

    def stop_agent_auth(self) -> None:
        """Stop the sibling ``agent-auth`` container without tearing down the bridge.

        Used to exercise the ``authz_unavailable`` path end-to-end: the
        bridge stays up and keeps serving requests, but its in-network
        upstream is gone so ``AgentAuthClient.validate`` surfaces a real
        connection error from the container runtime rather than a mock.
        The shared fixture teardown then runs ``compose down`` against
        the whole project, which is a no-op for already-stopped
        containers.
        """
        self.cluster.stop_service("agent-auth")


def _write_agent_auth_config(
    config_dir: Path,
    *,
    access_token_ttl_seconds: int,
    refresh_token_ttl_seconds: int,
) -> None:
    """Mirror ``tests.integration.conftest._write_test_config`` for the
    multi-service stack.

    Kept local rather than re-importing the private helper so the
    bridge fixture is self-contained when this module is read in
    isolation, and so the bridge factory can choose its own approval
    default without touching the agent-auth-only fixture.
    """
    with BASELINE_CONFIG.open() as f:
        config = yaml.safe_load(f) or {}
    # Under #6 the notifier runs as a sidecar container; the URL is
    # fixed across tests and the approve/deny variant is chosen by the
    # NOTIFIER_MODE env var passed to docker compose (see
    # APPROVAL_PLUGINS in tests/integration/conftest.py).
    config["notification_plugin_url"] = "http://notifier:9150/"
    config["access_token_ttl_seconds"] = access_token_ttl_seconds
    config["refresh_token_ttl_seconds"] = refresh_token_ttl_seconds
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    os.chmod(config_dir, 0o755)
    os.chmod(config_path, 0o644)


def _things_bridge_cluster(
    *,
    project_name: str,
    image_tags: dict[str, str],
    config_dir: Path,
    fixtures_dir: Path,
    notifier_mode: str,
    logs_dir: Path,
) -> DockerComposeCluster:
    """Build the per-test cluster definition with both service waits wired up.

    Uses the same compose file as the agent-auth-only fixture, but adds
    a readiness probe for the ``things-bridge`` service so the wait
    loop blocks until both HTTP surfaces answer.
    """
    builder = (
        DockerComposeCluster.builder()
        .project_name(project_name)
        .file(COMPOSE_FILE)
        .env("AGENT_AUTH_TEST_CONFIG_DIR", str(config_dir))
        .env("THINGS_BRIDGE_TEST_FIXTURES_DIR", str(fixtures_dir))
        .env("NOTIFIER_MODE", notifier_mode)
    )
    for key, value in _compose_image_env(image_tags).items():
        builder = builder.env(key, value)
    return (
        builder.waiting_for_service(
            "agent-auth",
            HealthChecks.to_respond_over_http(
                internal_port=AGENT_AUTH_INTERNAL_PORT,
                url_format="http://$HOST:$EXTERNAL_PORT/agent-auth/health",
                accept_statuses={401, 403},
            ),
        )
        .waiting_for_service(
            "things-bridge",
            HealthChecks.to_respond_over_http(
                internal_port=THINGS_BRIDGE_INTERNAL_PORT,
                url_format="http://$HOST:$EXTERNAL_PORT/things-bridge/health",
                accept_statuses={401, 403},
            ),
        )
        .save_logs_to(logs_dir, on_success=False)
        .build()
    )


@pytest.fixture
def things_bridge_stack_factory(
    _test_image_tags: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Generator[Callable[..., ThingsBridgeStack], None, None]:
    """Factory fixture — spin up the agent-auth + things-bridge pair.

    Each invocation starts a fresh Compose project (per-test UUID).
    Teardown is registered on the fixture so every cluster is stopped
    at the end of the test.
    """
    started: list[StartedCluster] = []

    def _factory(
        *,
        approval: str = "approve",
        access_token_ttl_seconds: int = 900,
        refresh_token_ttl_seconds: int = 28800,
    ) -> ThingsBridgeStack:
        if approval not in APPROVAL_PLUGINS:
            raise ValueError(
                f"unknown approval mode {approval!r}; expected one of "
                f"{sorted(APPROVAL_PLUGINS)}"
            )

        project_name = f"things-bridge-it-{uuid.uuid4().hex[:12]}"
        agent_auth_config_dir = tmp_path_factory.mktemp(f"aa-cfg-{project_name}")
        fixtures_dir = tmp_path_factory.mktemp(f"tb-fix-{project_name}")
        logs_dir = tmp_path_factory.mktemp(f"logs-{project_name}")

        _write_agent_auth_config(
            agent_auth_config_dir,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
        )
        # Seed an empty fixture so the fake CLI starts cleanly even
        # before a test writes its own data.
        seed_empty_fixtures_dir(fixtures_dir)

        cluster = _things_bridge_cluster(
            project_name=project_name,
            image_tags=_test_image_tags,
            config_dir=agent_auth_config_dir,
            fixtures_dir=fixtures_dir,
            notifier_mode=APPROVAL_PLUGINS[approval],
            logs_dir=logs_dir,
        )
        with phase_timer("compose_start", project=project_name, service="things-bridge"):
            running = cluster.start()
        started.append(running)

        bridge_port = running.service("things-bridge").port(THINGS_BRIDGE_INTERNAL_PORT)
        base_url = bridge_port.in_format("http://$HOST:$EXTERNAL_PORT")
        # Build an AgentAuthContainer handle so tests can mint tokens
        # via the in-container CLI. ``agent-auth`` is reached only
        # over the internal Compose network; no host-port mapping
        # for it is required.
        agent_auth = AgentAuthContainer(
            base_url="http://agent-auth:9100",  # internal only; CLI doesn't use it
            cluster=running,
            service="agent-auth",
        )
        return ThingsBridgeStack(
            base_url=base_url,
            cluster=running,
            agent_auth=agent_auth,
            fixtures_dir=fixtures_dir,
        )

    yield _factory

    failed = _test_failed(request)
    for running in started:
        try:
            with phase_timer("compose_stop", project=running.project_name, service="things-bridge"):
                running.stop(test_failed=failed)
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def things_bridge_stack(
    things_bridge_stack_factory: Callable[..., ThingsBridgeStack],
) -> ThingsBridgeStack:
    """Default integration fixture — auto-approve plugin so JIT prompts
    for ``things:read`` complete without host interaction."""
    return things_bridge_stack_factory()
