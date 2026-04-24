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
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from testcontainers.compose import DockerCompose

from agent_auth_client import AgentAuthClient
from tests.integration._support import (
    DOCKER_DIR,
    PER_SERVICE_DOCKERFILES,
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
# onto the sidecar notifier mode (see docker/docker-compose.yaml).
# Under #6 the notifier is a separate container the compose file
# launches per-test; the URL the agent-auth container POSTs to is
# the same regardless of mode.
APPROVAL_PLUGINS = {
    "approve": "approve",
    "deny": "deny",
}

# The sidecar binds to 0.0.0.0:9150 inside the compose network and
# every test's agent-auth container resolves ``notifier`` via Docker
# DNS.
NOTIFIER_SIDECAR_URL = "http://notifier:9150/"


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
    _client_cache: AgentAuthClient | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def client(self) -> AgentAuthClient:
        """Return a shared :class:`AgentAuthClient` bound to this container."""
        if self._client_cache is None:
            self._client_cache = AgentAuthClient(self.base_url, timeout_seconds=10.0)
        return self._client_cache

    def management_token(self) -> str:
        """Return a valid management access token, refreshed from keyring on first call."""
        if self._mgmt_token_cache is None:
            result = json.loads(self.exec_cli("--json", "management-token", "show"))
            refreshed = self.client().refresh(result["refresh_token"])
            self._mgmt_token_cache = refreshed.access_token
        assert self._mgmt_token_cache is not None
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
        return cast(str, stdout)

    def create_token(self, *scopes: str) -> dict[str, Any]:
        """Create a token family inside the container and return the parsed JSON.

        Uses the ``agent-auth`` CLI — not the HTTP client — because the
        management refresh token is stored in the container's keyring
        and never crosses the HTTP boundary. Tests that specifically
        need to exercise ``POST /token/create`` do so through
        :meth:`client` with the token returned by
        :meth:`management_token`.
        """
        if not scopes:
            raise ValueError("at least one scope required")
        scope_args = []
        for scope in scopes:
            scope_args.extend(["--scope", scope])
        return cast(
            dict[str, Any], json.loads(self.exec_cli("--json", "token", "create", *scope_args))
        )

    def list_families(self) -> list[dict[str, Any]]:
        """Return all token families via ``agent-auth token list --json``."""
        return cast(list[dict[str, Any]], json.loads(self.exec_cli("--json", "token", "list")))

    def get_family(self, family_id: str) -> dict[str, Any] | None:
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


def _resolve_test_image_tags() -> tuple[dict[str, str], bool]:
    """Resolve the per-service image tags for this session.

    Returns ``(tags, managed)``. ``tags`` maps each service name (as
    used in :data:`PER_SERVICE_DOCKERFILES`) to the full ``name:tag``
    reference callers should pass to ``docker compose``. ``managed`` is
    ``True`` when the caller must build and clean up the images,
    ``False`` when they were supplied externally by a CI step that ran
    ``docker build`` itself.

    External override is ``AGENT_AUTH_TEST_IMAGE_SESSION``: a non-empty
    string is used verbatim as the shared tag suffix across every
    per-service image (e.g. ``ci`` → ``agent-auth-test:ci``,
    ``things-bridge-test:ci``, …). The managed case picks a
    per-session random suffix so parallel sessions (two worktrees, two
    CI jobs sharing a runner) don't clobber each other's images under
    a shared mutable tag.
    """
    prebuilt = os.environ.get("AGENT_AUTH_TEST_IMAGE_SESSION")
    if prebuilt:
        return _tags_from_suffix(prebuilt), False
    return _tags_from_suffix(f"pytest-{uuid.uuid4().hex[:8]}"), True


def _tags_from_suffix(suffix: str) -> dict[str, str]:
    """Return the per-service image tag map anchored at ``suffix``."""
    return {service: f"{service}-test:{suffix}" for service in PER_SERVICE_DOCKERFILES}


@pytest.fixture(scope="session")
def _test_image_tags(_docker_required):
    """Yield the per-service integration-test image tags for this session.

    Builds and cleans up every image the fixture owns; in the externally-
    supplied path (CI), the images are left to the caller. A managed
    build is sequenced per-service so a failure surfaces the failing
    Dockerfile in the traceback rather than an aggregated error.
    """
    tags, managed = _resolve_test_image_tags()
    if not managed:
        yield tags
        return
    for service, tag in tags.items():
        build_test_image(PER_SERVICE_DOCKERFILES[service], tag)
    try:
        yield tags
    finally:
        for tag in tags.values():
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
    ``docker/Dockerfile.agent-auth.test``), while ``tmp_path_factory.mktemp`` on
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
    _test_image_tags: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Callable[..., AgentAuthContainer], None, None]:
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
            notification_plugin_url=NOTIFIER_SIDECAR_URL,
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
            AGENT_AUTH_TEST_IMAGE=_test_image_tags["agent-auth"],
            THINGS_BRIDGE_TEST_IMAGE=_test_image_tags["things-bridge"],
            THINGS_CLI_TEST_IMAGE=_test_image_tags["things-cli"],
            AGENT_AUTH_TEST_CONFIG_DIR=str(config_dir),
            THINGS_BRIDGE_TEST_FIXTURES_DIR=str(bridge_fixtures_dir),
            NOTIFIER_MODE=APPROVAL_PLUGINS[approval],
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
def agent_auth_container(
    agent_auth_container_factory: Callable[..., AgentAuthContainer],
) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
