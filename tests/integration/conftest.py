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
import os
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from testcontainers.compose import DockerCompose

from tests.integration._support import (
    COMPOSE_FILE_NAME,
    DOCKER_DIR,
    build_test_image,
    docker_compose_available,
    scoped_env,
    seed_empty_fixtures_dir,
    wait_until_server_ready,
    write_bridge_config,
)

BASELINE_CONFIG = DOCKER_DIR / "config.test.json"

# Maps the integration-test factory's human-readable ``approval`` knob
# onto the fully-qualified notification-plugin module the container
# should load. Tests pass ``approve`` / ``deny``; the plugin name is
# written into the per-test config.json.
APPROVAL_PLUGINS = {
    "approve": "tests_support.always_approve",
    "deny": "tests_support.always_deny",
}


@dataclass
class AgentAuthContainer:
    """Handle for a running agent-auth integration-test container.

    ``env`` is the per-project ``{AGENT_AUTH_TEST_CONFIG_DIR,
    COMPOSE_PROJECT_NAME}`` pair this container was started with. It is
    reapplied via ``scoped_env`` around every ``docker compose exec``
    call because testcontainers invokes ``docker compose`` without an
    explicit ``env=``, so each subprocess inherits whatever
    ``os.environ`` holds at call time — and the compose file needs
    ``${AGENT_AUTH_TEST_CONFIG_DIR}`` interpolated on every exec.
    """

    base_url: str
    compose: DockerCompose
    env: dict[str, str]
    service: str = "agent-auth"

    def url(self, path: str) -> str:
        """Return ``{base_url}/agent-auth/{path}``."""
        return f"{self.base_url}/agent-auth/{path.lstrip('/')}"

    def exec_cli(self, *args: str) -> str:
        """Run ``agent-auth <args>`` inside the container and return stdout.

        Raises ``RuntimeError`` with stdout/stderr interpolated on non-zero
        exit so pytest tracebacks show *why* the CLI failed rather than an
        opaque ``CalledProcessError``.
        """
        with scoped_env(**self.env):
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


@pytest.fixture(scope="session")
def _test_image_tag(_docker_required):
    """Build the integration-test image once per pytest session under a
    session-unique tag, then clean it up on teardown.

    A unique tag prevents parallel sessions (two worktrees, two CI jobs
    sharing a runner) from clobbering each other's image under a shared
    mutable tag — without which one session could boot another's image
    while still using its own Compose project.
    """
    tag = f"agent-auth-test:pytest-{uuid.uuid4().hex[:8]}"
    build_test_image(tag)
    previous = os.environ.get("AGENT_AUTH_TEST_IMAGE")
    os.environ["AGENT_AUTH_TEST_IMAGE"] = tag
    try:
        yield tag
    finally:
        if previous is None:
            os.environ.pop("AGENT_AUTH_TEST_IMAGE", None)
        else:
            os.environ["AGENT_AUTH_TEST_IMAGE"] = previous
        subprocess.run(
            ["docker", "rmi", "-f", tag],
            capture_output=True,
            check=False,
            timeout=60,
        )


def _write_test_config(config_dir: Path, **overrides: object) -> None:
    """Copy the baseline ``config.test.json`` into ``config_dir/config.json``
    with ``overrides`` applied on top.

    The directory and file are chmod'd world-readable because the config
    is bind-mounted into a container that runs as UID 1001 (see
    ``docker/Dockerfile.test``), while ``tmp_path_factory.mktemp`` on
    Linux defaults to mode 0700 owned by the host test runner's UID. If
    those UIDs disagree (common in devcontainers and some CI configs)
    the container user cannot read ``config.json`` and ``agent-auth
    serve`` fails on startup. No secrets live in the test config.
    """
    with BASELINE_CONFIG.open() as f:
        config = json.load(f)
    config.update(overrides)
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    os.chmod(config_dir, 0o755)
    os.chmod(config_path, 0o644)


@dataclass
class _StartedCompose:
    """A running compose project plus the env vars its lifecycle needs.

    ``env`` is reapplied (via ``scoped_env``) around every subsequent
    subprocess call on ``compose`` — notably ``stop()`` in teardown — so
    the right ``COMPOSE_PROJECT_NAME`` always wins regardless of ordering.
    """

    compose: DockerCompose
    env: dict[str, str] = field(default_factory=dict)


@pytest.fixture
def agent_auth_container_factory(
    _test_image_tag,
    tmp_path_factory,
) -> Callable[..., AgentAuthContainer]:
    """Factory fixture — spin up an agent-auth container with custom config.

    Each invocation starts a fresh Compose project. Teardown is registered
    on the fixture so every container is removed at the end of the test.
    """
    started: list[_StartedCompose] = []

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
        # container alongside agent-auth, so we must satisfy its bind
        # mounts even for tests that never call the bridge. Provision
        # the baseline bridge config and an empty fixtures dir; tests
        # that exercise the bridge use the things_bridge_stack fixture
        # which writes its own state.
        bridge_config_dir = tmp_path_factory.mktemp(f"tb-cfg-{project_name}")
        bridge_fixtures_dir = tmp_path_factory.mktemp(f"tb-fix-{project_name}")
        write_bridge_config(bridge_config_dir)
        seed_empty_fixtures_dir(bridge_fixtures_dir)

        compose_env = {
            "AGENT_AUTH_TEST_CONFIG_DIR": str(config_dir),
            "THINGS_BRIDGE_TEST_CONFIG_DIR": str(bridge_config_dir),
            "THINGS_BRIDGE_TEST_FIXTURES_DIR": str(bridge_fixtures_dir),
            "COMPOSE_PROJECT_NAME": project_name,
        }

        compose = DockerCompose(
            context=str(DOCKER_DIR),
            compose_file_name=COMPOSE_FILE_NAME,
        )
        started.append(_StartedCompose(compose=compose, env=compose_env))
        with scoped_env(**compose_env):
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
                env=compose_env,
            )

    yield _factory

    for entry in started:
        try:
            with scoped_env(**entry.env):
                entry.compose.stop()
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def agent_auth_container(agent_auth_container_factory) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
