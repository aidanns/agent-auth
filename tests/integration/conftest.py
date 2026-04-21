# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Docker-backed fixtures for agent-auth integration tests.

Each test that requests the fixture gets a fresh Compose project (named
by a per-test UUID), giving it an isolated container, ephemeral host
port, and filesystem. The test talks to the mapped loopback port and
drives state through the agent-auth HTTP API + the ``agent-auth`` CLI
running inside the container.

The Compose lifecycle is managed by ``testcontainers-python``; the
session-scoped image build remains a direct ``docker build`` call so the
test image is rebuilt once per pytest run off the working tree.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml
from testcontainers.compose import DockerCompose

from tests._http import post
from tests.integration._support import (
    DOCKER_DIR,
    build_test_image,
    docker_compose_available,
    phase_timer,
    render_compose_file,
    seed_empty_fixtures_dir,
    wait_until_server_ready,
)

# The integration runner enables ``log_cli_level=INFO`` so the
# ``integration.timing`` phase logs stream live. The HTTP / docker
# plumbing libraries log at INFO too, which drowns the phase rows
# under noise unrelated to timing. Raise their floors to WARNING so
# the CI log stays grep-friendly. Done unconditionally because this
# module is only imported when the integration suite runs.
for _noisy_logger in ("docker", "urllib3", "testcontainers", "asyncio"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

BASELINE_CONFIG = DOCKER_DIR / "config.test.yaml"

# Maps the integration-test factory's human-readable ``approval`` knob
# onto the fully-qualified notification-plugin module the container
# should load. Tests pass ``approve`` / ``deny``; the plugin name is
# written into the per-test config.yaml.
APPROVAL_PLUGINS = {
    "approve": "tests_support.always_approve",
    "deny": "tests_support.always_deny",
}


@dataclass
class AgentAuthContainer:
    """Handle for a running agent-auth integration-test container.

    The compose file is rendered per-test (every placeholder is
    substituted in Python before docker compose ever sees the file), so
    no env-var inheritance is required around ``exec_in_container`` or
    teardown calls.
    """

    base_url: str
    compose: DockerCompose
    service: str = "agent-auth"
    _mgmt_token_cache: str | None = field(default=None, init=False, repr=False, compare=False)

    def url(self, path: str) -> str:
        """Return ``{base_url}/agent-auth/v1/{path}``."""
        return f"{self.base_url}/agent-auth/v1/{path.lstrip('/')}"

    def health_url(self) -> str:
        """Return the unversioned health endpoint URL."""
        return f"{self.base_url}/agent-auth/health"

    def management_token(self) -> str:
        """Return a valid management access token, refreshed from keyring on first call."""
        if self._mgmt_token_cache is None:
            result = json.loads(self.exec_cli("--json", "management-token", "show"))
            _, body = post(self.url("token/refresh"), {"refresh_token": result["refresh_token"]})
            self._mgmt_token_cache = body["access_token"]
        return self._mgmt_token_cache

    def exec_cli(self, *args: str) -> str:
        """Run ``agent-auth <args>`` inside the container and return stdout.

        Raises ``RuntimeError`` with stdout/stderr interpolated on non-zero
        exit so pytest tracebacks show *why* the CLI failed rather than an
        opaque ``CalledProcessError``.
        """
        stdout, stderr, exit_code = self.compose.exec_in_container(
            ["agent-auth", *args],
            service_name=self.service,
        )
        if exit_code != 0:
            raise RuntimeError(
                f"`agent-auth {' '.join(args)}` failed: "
                f"exit={exit_code} stdout={stdout!r} stderr={stderr!r}"
            )
        return stdout

    def create_token(self, *scopes: str) -> dict:
        """Create a token family inside the container and return the parsed JSON."""
        if not scopes:
            raise ValueError("at least one scope required")
        scope_args = []
        for scope in scopes:
            scope_args.extend(["--scope", scope])
        return json.loads(self.exec_cli("--json", "token", "create", *scope_args))

    def list_families(self) -> list[dict]:
        """Return all token families via ``agent-auth token list --json``."""
        return json.loads(self.exec_cli("--json", "token", "list"))

    def get_family(self, family_id: str) -> dict | None:
        """Return a single family by id, or None if not present."""
        return next(
            (f for f in self.list_families() if f["id"] == family_id),
            None,
        )


@pytest.fixture(scope="session")
def _docker_required():
    if not docker_compose_available():
        pytest.skip(
            "docker + docker compose are required for integration tests; "
            "skipping (run `scripts/test.sh --integration` on a host with Docker)"
        )


def _resolve_test_image_tag() -> tuple[str, bool]:
    """Resolve the image tag to use this session and whether to own it.

    Returns ``(tag, managed)``. ``managed`` is ``True`` when the caller
    must build and clean up the image, ``False`` when the tag was
    supplied externally (typically via ``AGENT_AUTH_TEST_IMAGE_TAG`` set
    by a CI step that ran ``docker build`` itself) and the caller must
    not build or remove it.

    A session-unique tag in the managed case prevents parallel sessions
    (two worktrees, two CI jobs sharing a runner) from clobbering each
    other's image under a shared mutable tag — without which one
    session could boot another's image while still using its own
    Compose project.
    """
    prebuilt = os.environ.get("AGENT_AUTH_TEST_IMAGE_TAG")
    if prebuilt:
        return prebuilt, False
    return f"agent-auth-test:pytest-{uuid.uuid4().hex[:8]}", True


@pytest.fixture(scope="session")
def _test_image_tag(_docker_required):
    """Yield the integration-test image tag for this session, building
    and cleaning it up when the fixture owns the image."""
    tag, managed = _resolve_test_image_tag()
    if not managed:
        yield tag
        return
    build_test_image(tag)
    try:
        yield tag
    finally:
        subprocess.run(
            ["docker", "rmi", "-f", tag],
            capture_output=True,
            check=False,
            timeout=60,
        )


def _write_test_config(config_dir: Path, **overrides: object) -> None:
    """Copy the baseline ``config.test.yaml`` into ``config_dir/config.yaml``
    with ``overrides`` applied on top.

    The directory and file are chmod'd world-readable because the config
    is bind-mounted into a container that runs as UID 1001 (see
    ``docker/Dockerfile.test``), while ``tmp_path_factory.mktemp`` on
    Linux defaults to mode 0700 owned by the host test runner's UID. If
    those UIDs disagree (common in devcontainers and some CI configs)
    the container user cannot read ``config.yaml`` and ``agent-auth
    serve`` fails on startup. No secrets live in the test config.
    """
    with BASELINE_CONFIG.open() as f:
        config = yaml.safe_load(f) or {}
    config.update(overrides)
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    os.chmod(config_dir, 0o755)
    os.chmod(config_path, 0o644)


@pytest.fixture
def agent_auth_container_factory(
    _test_image_tag,
    tmp_path_factory,
) -> Callable[..., AgentAuthContainer]:
    """Factory fixture — spin up an agent-auth container with custom config.

    Each invocation starts a fresh Compose project. Teardown is registered
    on the fixture so every container is removed at the end of the test.
    """
    started: list[tuple[str, DockerCompose]] = []

    def _factory(
        *,
        approval: str = "deny",
        access_token_ttl_seconds: int = 900,
        refresh_token_ttl_seconds: int = 28800,
    ) -> AgentAuthContainer:
        if approval not in APPROVAL_PLUGINS:
            raise ValueError(
                f"unknown approval mode {approval!r}; expected one of "
                f"{sorted(APPROVAL_PLUGINS)}"
            )

        project_name = f"agent-auth-it-{uuid.uuid4().hex[:12]}"
        config_dir = tmp_path_factory.mktemp(f"cfg-{project_name}")
        _write_test_config(
            config_dir,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
            notification_plugin=APPROVAL_PLUGINS[approval],
        )

        # The combined Compose file always starts the things-bridge
        # container alongside agent-auth (its config is shipped inline
        # by docker-compose.yaml), so we only need to satisfy the
        # fixtures bind mount even when this test never drives the
        # bridge. Tests that exercise the bridge use the
        # things_bridge_stack fixture which writes its own fixture data.
        bridge_fixtures_dir = tmp_path_factory.mktemp(f"tb-fix-{project_name}")
        seed_empty_fixtures_dir(bridge_fixtures_dir)

        rendered_compose = render_compose_file(
            tmp_path_factory.mktemp(f"compose-{project_name}"),
            COMPOSE_PROJECT_NAME=project_name,
            AGENT_AUTH_TEST_IMAGE=_test_image_tag,
            AGENT_AUTH_TEST_CONFIG_DIR=str(config_dir),
            THINGS_BRIDGE_TEST_FIXTURES_DIR=str(bridge_fixtures_dir),
        )

        compose = DockerCompose(
            context=str(rendered_compose.parent),
            compose_file_name=rendered_compose.name,
        )
        started.append((project_name, compose))
        with phase_timer("compose_start", project=project_name, service="agent-auth"):
            compose.start()

        host = compose.get_service_host("agent-auth", 9100)
        port = compose.get_service_port("agent-auth", 9100)
        base_url = f"http://{host}:{port}"
        # /agent-auth/health requires an ``agent-auth:health`` token,
        # so an unauthenticated probe gets 401 (or 403 if the scope
        # check ran). Either is a positive "server is up" signal.
        wait_until_server_ready(
            f"{base_url}/agent-auth/health",
            accept_status=(401, 403),
        )
        return AgentAuthContainer(
            base_url=base_url,
            compose=compose,
        )

    yield _factory

    for project_name, compose in started:
        try:
            with phase_timer("compose_stop", project=project_name, service="agent-auth"):
                compose.stop()
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def agent_auth_container(agent_auth_container_factory) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
