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
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from testcontainers.compose import DockerCompose


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
COMPOSE_FILE_NAME = "compose.test.yaml"
DOCKERFILE = DOCKER_DIR / "Dockerfile.test"
BASELINE_CONFIG = DOCKER_DIR / "config.test.json"

DOCKER_BUILD_TIMEOUT_SECONDS = 600.0
READY_POLL_TIMEOUT_SECONDS = 30.0
READY_POLL_INTERVAL_SECONDS = 0.2

# Maps the integration-test factory's human-readable ``approval`` knob
# onto the fully-qualified notification-plugin module the container
# should load. Tests pass ``approve`` / ``deny``; the plugin name is
# written into the per-test config.json.
APPROVAL_PLUGINS = {
    "approve": "tests_support.always_approve",
    "deny": "tests_support.always_deny",
}


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return True


@dataclass
class AgentAuthContainer:
    """Handle for a running agent-auth integration-test container."""

    base_url: str
    compose: DockerCompose
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
    if not _docker_compose_available():
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
    result = subprocess.run(
        [
            "docker", "build",
            "-f", str(DOCKERFILE),
            "-t", tag,
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`docker build` failed for {tag}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
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


def _wait_until_server_ready(health_url: str) -> None:
    """Block until the server binds its port and answers ``health_url``.

    The endpoint requires an ``agent-auth:health`` token, so an
    unauthenticated probe returns ``401``. Treat that — along with
    ``403`` (valid shape, scope missing) — as a positive "server is up"
    signal; the per-test token creation that follows exercises the full
    auth path.
    """
    deadline = time.monotonic() + READY_POLL_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return
            last_error = e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_error = e
        time.sleep(READY_POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"agent-auth container never became reachable at {health_url} "
        f"within {READY_POLL_TIMEOUT_SECONDS}s (last error: {last_error!r})"
    )


def _write_test_config(config_dir: Path, **overrides: object) -> None:
    """Copy the baseline ``config.test.json`` into ``config_dir/config.json``
    with ``overrides`` applied on top."""
    with BASELINE_CONFIG.open() as f:
        config = json.load(f)
    config.update(overrides)
    (config_dir / "config.json").write_text(json.dumps(config, indent=2))


@pytest.fixture
def agent_auth_container_factory(
    _test_image_tag,
    tmp_path_factory,
) -> Callable[..., AgentAuthContainer]:
    """Factory fixture — spin up an agent-auth container with custom config.

    Each invocation starts a fresh Compose project. Teardown is registered
    on the fixture so every container is removed at the end of the test.
    """
    started: list[DockerCompose] = []

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

        # The compose subprocess inherits this process's environment, so
        # setting the variables here is enough for Compose's
        # interpolation (``${AGENT_AUTH_TEST_IMAGE}``,
        # ``${AGENT_AUTH_TEST_CONFIG_DIR}``) and for per-test project
        # isolation via ``COMPOSE_PROJECT_NAME``.
        os.environ["AGENT_AUTH_TEST_CONFIG_DIR"] = str(config_dir)
        os.environ["COMPOSE_PROJECT_NAME"] = project_name

        compose = DockerCompose(
            context=str(DOCKER_DIR),
            compose_file_name=COMPOSE_FILE_NAME,
        )
        # Register before start so a partial failure still tears resources
        # down (ports/volumes/networks can be created before up exits
        # non-zero).
        started.append(compose)
        compose.start()

        host = compose.get_service_host("agent-auth", 9100)
        port = compose.get_service_port("agent-auth", 9100)
        base_url = f"http://{host}:{port}"
        _wait_until_server_ready(f"{base_url}/agent-auth/health")
        return AgentAuthContainer(base_url=base_url, compose=compose)

    yield _factory

    for compose in started:
        try:
            compose.stop()
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def agent_auth_container(agent_auth_container_factory) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
