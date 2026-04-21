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
import subprocess
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from testcontainers.compose import DockerCompose

from tests.integration._support import (
    phase_timer,
    render_compose_file,
    seed_empty_fixtures_dir,
    wait_until_server_ready,
)
from tests.integration.conftest import (
    APPROVAL_PLUGINS,
    BASELINE_CONFIG,
    AgentAuthContainer,
)

AGENT_AUTH_PORT = 9100
THINGS_BRIDGE_PORT = 9200


@dataclass
class ThingsBridgeStack:
    """Handle for a running ``agent-auth`` + ``things-bridge`` Compose pair.

    The stack is exposed to tests through the bridge's host-mapped
    loopback port. ``agent_auth`` is the in-container handle used to
    mint and revoke tokens.

    ``compose_file`` is the per-test rendered compose file path; the
    project name is baked into it (compose v2 ``name:`` field), so
    callers that shell out to ``docker compose -f ...`` don't need any
    env-var inheritance to address the right project.
    """

    base_url: str
    bridge_compose: DockerCompose
    agent_auth: AgentAuthContainer
    fixtures_dir: Path
    compose_file: str

    def url(self, path: str) -> str:
        """Return ``{base_url}/things-bridge/v1/{path}``."""
        return f"{self.base_url}/things-bridge/v1/{path.lstrip('/')}"

    def health_url(self) -> str:
        """Return the unversioned health endpoint URL."""
        return f"{self.base_url}/things-bridge/health"

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
        subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "stop", "agent-auth"],
            check=True,
            capture_output=True,
            timeout=30,
        )


def _write_agent_auth_config(
    config_dir: Path,
    *,
    approval: str,
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
    config["notification_plugin"] = APPROVAL_PLUGINS[approval]
    config["access_token_ttl_seconds"] = access_token_ttl_seconds
    config["refresh_token_ttl_seconds"] = refresh_token_ttl_seconds
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    os.chmod(config_dir, 0o755)
    os.chmod(config_path, 0o644)


@pytest.fixture
def things_bridge_stack_factory(
    _test_image_tag: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Callable[..., ThingsBridgeStack], None, None]:
    """Factory fixture — spin up the agent-auth + things-bridge pair.

    Each invocation starts a fresh Compose project (per-test UUID).
    Teardown is registered on the fixture so every container is removed
    at the end of the test.
    """
    started: list[tuple[str, DockerCompose]] = []

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

        _write_agent_auth_config(
            agent_auth_config_dir,
            approval=approval,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
        )
        # Seed an empty fixture so the fake CLI starts cleanly even
        # before a test writes its own data.
        seed_empty_fixtures_dir(fixtures_dir)

        rendered_compose = render_compose_file(
            tmp_path_factory.mktemp(f"compose-{project_name}"),
            COMPOSE_PROJECT_NAME=project_name,
            AGENT_AUTH_TEST_IMAGE=_test_image_tag,
            AGENT_AUTH_TEST_CONFIG_DIR=str(agent_auth_config_dir),
            THINGS_BRIDGE_TEST_FIXTURES_DIR=str(fixtures_dir),
        )

        compose = DockerCompose(
            context=str(rendered_compose.parent),
            compose_file_name=rendered_compose.name,
        )
        started.append((project_name, compose))
        with phase_timer("compose_start", project=project_name, service="things-bridge"):
            compose.start()

        bridge_host = compose.get_service_host("things-bridge", THINGS_BRIDGE_PORT)
        bridge_port = compose.get_service_port("things-bridge", THINGS_BRIDGE_PORT)
        base_url = f"http://{bridge_host}:{bridge_port}"
        # /things-bridge/health requires a ``things-bridge:health`` token;
        # an unauthenticated probe gets 401 (or 403 if the scope check
        # ran), which is a positive "server is up" signal — same pattern
        # as the agent-auth probe.
        wait_until_server_ready(
            f"{base_url}/things-bridge/health",
            accept_status=(401, 403),
        )

        # Build an AgentAuthContainer handle so tests can mint tokens
        # via the in-container CLI. ``agent-auth`` is reached only
        # over the internal Compose network; no host-port mapping
        # for it is required.
        agent_auth = AgentAuthContainer(
            base_url="http://agent-auth:9100",  # internal only; CLI doesn't use it
            compose=compose,
            service="agent-auth",
        )

        return ThingsBridgeStack(
            base_url=base_url,
            bridge_compose=compose,
            agent_auth=agent_auth,
            fixtures_dir=fixtures_dir,
            compose_file=str(rendered_compose),
        )

    yield _factory

    for project_name, compose in started:
        try:
            with phase_timer("compose_stop", project=project_name, service="things-bridge"):
                compose.stop()
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def things_bridge_stack(
    things_bridge_stack_factory: Callable[..., ThingsBridgeStack],
) -> ThingsBridgeStack:
    """Default integration fixture — auto-approve plugin so JIT prompts
    for ``things:read`` complete without host interaction."""
    return things_bridge_stack_factory()
