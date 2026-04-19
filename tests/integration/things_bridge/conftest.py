"""Docker-backed fixtures for things-bridge integration tests.

Each test gets its own multi-service Compose project (an ``agent-auth``
service for token validation plus a ``things-bridge`` service for the
HTTP surface under test). The bridge invokes the in-tree fake Things
client subprocess, fed by a YAML fixture the per-test fixture writes
into a bind-mounted directory.

Tests address the bridge through its host-mapped loopback port; the
``agent-auth`` service is reached only via the in-container ``agent-auth``
CLI (used here to mint scoped tokens).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest
import yaml
from testcontainers.compose import DockerCompose

from tests.integration._support import (
    DOCKER_DIR,
    scoped_env,
    wait_until_server_ready,
)
from tests.integration.conftest import (
    APPROVAL_PLUGINS,
    AgentAuthContainer,
    BASELINE_CONFIG,
)


COMPOSE_FILE_NAME = "compose.test.things-bridge.yaml"
BRIDGE_BASELINE_CONFIG = DOCKER_DIR / "config.test.things-bridge.yaml"
AGENT_AUTH_PORT = 9100
THINGS_BRIDGE_PORT = 9200


@dataclass
class ThingsBridgeStack:
    """Handle for a running ``agent-auth`` + ``things-bridge`` Compose pair.

    The stack is exposed to tests through the bridge's host-mapped
    loopback port. ``agent_auth`` is the in-container handle used to
    mint and revoke tokens.
    """

    base_url: str
    bridge_compose: DockerCompose
    bridge_env: dict[str, str]
    agent_auth: AgentAuthContainer
    fixtures_dir: Path

    def url(self, path: str) -> str:
        """Return ``{base_url}/things-bridge/{path}``."""
        return f"{self.base_url}/things-bridge/{path.lstrip('/')}"

    def write_fixture(self, fixture: dict) -> None:
        """Write/replace ``things.yaml`` in the bind-mounted fixtures dir."""
        path = self.fixtures_dir / "things.yaml"
        path.write_text(yaml.safe_dump(fixture))
        os.chmod(path, 0o644)


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
        config = json.load(f)
    config["notification_plugin"] = APPROVAL_PLUGINS[approval]
    config["access_token_ttl_seconds"] = access_token_ttl_seconds
    config["refresh_token_ttl_seconds"] = refresh_token_ttl_seconds
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    os.chmod(config_dir, 0o755)
    os.chmod(config_path, 0o644)


def _write_bridge_config(config_dir: Path) -> None:
    """Copy the baseline bridge config into ``config_dir/config.yaml``.

    The config bind-mounts into the bridge container; mode bits must be
    world-readable for the same UID-mismatch reason documented on the
    agent-auth fixture.
    """
    target = config_dir / "config.yaml"
    shutil.copyfile(BRIDGE_BASELINE_CONFIG, target)
    os.chmod(config_dir, 0o755)
    os.chmod(target, 0o644)


@dataclass
class _StartedCompose:
    compose: DockerCompose
    env: dict[str, str] = field(default_factory=dict)


@pytest.fixture
def things_bridge_stack_factory(
    _test_image_tag,
    tmp_path_factory,
) -> Callable[..., ThingsBridgeStack]:
    """Factory fixture — spin up the agent-auth + things-bridge pair.

    Each invocation starts a fresh Compose project (per-test UUID).
    Teardown is registered on the fixture so every container is removed
    at the end of the test.
    """
    started: list[_StartedCompose] = []

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
        bridge_config_dir = tmp_path_factory.mktemp(f"tb-cfg-{project_name}")
        fixtures_dir = tmp_path_factory.mktemp(f"tb-fix-{project_name}")

        _write_agent_auth_config(
            agent_auth_config_dir,
            approval=approval,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
        )
        _write_bridge_config(bridge_config_dir)
        # Seed an empty fixture so the fake CLI starts cleanly even
        # before a test writes its own data.
        (fixtures_dir / "things.yaml").write_text("todos: []\n")
        os.chmod(fixtures_dir, 0o755)
        os.chmod(fixtures_dir / "things.yaml", 0o644)

        compose_env = {
            "AGENT_AUTH_TEST_CONFIG_DIR": str(agent_auth_config_dir),
            "THINGS_BRIDGE_TEST_CONFIG_DIR": str(bridge_config_dir),
            "THINGS_BRIDGE_TEST_FIXTURES_DIR": str(fixtures_dir),
            "COMPOSE_PROJECT_NAME": project_name,
        }

        compose = DockerCompose(
            context=str(DOCKER_DIR),
            compose_file_name=COMPOSE_FILE_NAME,
        )
        started.append(_StartedCompose(compose=compose, env=compose_env))
        with scoped_env(**compose_env):
            compose.start()

            bridge_host = compose.get_service_host("things-bridge", THINGS_BRIDGE_PORT)
            bridge_port = compose.get_service_port("things-bridge", THINGS_BRIDGE_PORT)
            base_url = f"http://{bridge_host}:{bridge_port}"
            wait_until_server_ready(
                f"{base_url}/things-bridge/health",
                accept_status=(),
            )

            # Build an AgentAuthContainer handle so tests can mint tokens
            # via the in-container CLI. ``agent-auth`` is reached only
            # over the internal Compose network; no host-port mapping
            # for it is required.
            agent_auth = AgentAuthContainer(
                base_url="http://agent-auth:9100",  # internal only; CLI doesn't use it
                compose=compose,
                env=compose_env,
                service="agent-auth",
            )

            return ThingsBridgeStack(
                base_url=base_url,
                bridge_compose=compose,
                bridge_env=compose_env,
                agent_auth=agent_auth,
                fixtures_dir=fixtures_dir,
            )

    yield _factory

    for entry in started:
        try:
            with scoped_env(**entry.env):
                entry.compose.stop()
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def things_bridge_stack(things_bridge_stack_factory) -> ThingsBridgeStack:
    """Default integration fixture — auto-approve plugin so JIT prompts
    for ``things:read`` complete without host interaction."""
    return things_bridge_stack_factory()
