"""Docker-backed fixtures for agent-auth integration tests.

Each test that requests the fixture gets a fresh Compose project (named
by a per-test UUID), which gives it an isolated container, ephemeral
host port, and filesystem. The test talks to the mapped loopback port
and drives state through the agent-auth HTTP API + the ``agent-auth``
CLI running inside the container.
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


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker" / "compose.test.yaml"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.test"

HEALTH_POLL_TIMEOUT_SECONDS = 30.0
HEALTH_POLL_INTERVAL_SECONDS = 0.2
DOCKER_COMPOSE_TIMEOUT_SECONDS = 120.0
DOCKER_BUILD_TIMEOUT_SECONDS = 600.0


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
    project_name: str
    service: str = "agent-auth"

    def url(self, path: str) -> str:
        """Return ``{base_url}/agent-auth/{path}``."""
        return f"{self.base_url}/agent-auth/{path.lstrip('/')}"

    def exec_cli(self, *args: str) -> subprocess.CompletedProcess:
        """Run ``agent-auth <args>`` inside the container and return the result.

        Raises ``RuntimeError`` with stdout/stderr interpolated on non-zero
        exit so pytest tracebacks show *why* the CLI failed rather than an
        opaque ``CalledProcessError``.
        """
        cmd = [
            "docker", "compose",
            "-f", str(COMPOSE_FILE),
            "-p", self.project_name,
            "exec", "-T", self.service,
            "agent-auth", *args,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=DOCKER_COMPOSE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"`agent-auth {' '.join(args)}` failed in {self.project_name}: "
                f"returncode={result.returncode} "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return result

    def create_token(self, *scopes: str) -> dict:
        """Create a token family inside the container and return the parsed JSON."""
        if not scopes:
            raise ValueError("at least one scope required")
        scope_args = []
        for scope in scopes:
            scope_args.extend(["--scope", scope])
        result = self.exec_cli("--json", "token", "create", *scope_args)
        return json.loads(result.stdout)

    def list_families(self) -> list[dict]:
        """Return all token families via ``agent-auth token list --json``."""
        result = self.exec_cli("--json", "token", "list")
        return json.loads(result.stdout)

    def get_family(self, family_id: str) -> dict | None:
        """Return a single family by id, or None if not present."""
        return next(
            (f for f in self.list_families() if f["id"] == family_id),
            None,
        )


def _compose(
    project_name: str,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = DOCKER_COMPOSE_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", project_name, *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
        timeout=timeout,
    )


def _mapped_port(project_name: str) -> int:
    result = _compose(project_name, "port", "agent-auth", "9100")
    if result.returncode != 0:
        raise RuntimeError(
            f"`docker compose port` failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    line = result.stdout.strip().splitlines()[-1]
    return int(line.rsplit(":", 1)[-1])


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + HEALTH_POLL_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/agent-auth/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_error = e
        time.sleep(HEALTH_POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"agent-auth container never reported healthy at {base_url}/agent-auth/health "
        f"within {HEALTH_POLL_TIMEOUT_SECONDS}s (last error: {last_error!r})"
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
    # Export for all `docker compose` subcommands — the compose file
    # interpolates ``${AGENT_AUTH_TEST_IMAGE}`` as the service image, so
    # `port`, `exec`, `down`, etc. all need it in the environment, not
    # just `up`.
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
            timeout=DOCKER_COMPOSE_TIMEOUT_SECONDS,
        )


@pytest.fixture
def agent_auth_container_factory(
    _test_image_tag,
) -> Callable[..., AgentAuthContainer]:
    """Factory fixture — spin up an agent-auth container with custom env.

    Each invocation starts a fresh Compose project. Teardown is registered
    on the fixture so every container is removed at the end of the test.
    """
    started: list[str] = []

    def _factory(
        *,
        approval: str = "deny",
        access_token_ttl_seconds: int = 900,
        refresh_token_ttl_seconds: int = 28800,
    ) -> AgentAuthContainer:
        project_name = f"agent-auth-it-{uuid.uuid4().hex[:12]}"
        env = {
            "AGENT_AUTH_TEST_APPROVAL": approval,
            "AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS": str(access_token_ttl_seconds),
            "AGENT_AUTH_REFRESH_TOKEN_TTL_SECONDS": str(refresh_token_ttl_seconds),
        }
        # Register the project before `up` so a partial failure still tears
        # resources down (ports/volumes/networks can be created before `up`
        # exits non-zero).
        started.append(project_name)
        up = _compose(project_name, "up", "-d", env=env)
        if up.returncode != 0:
            raise RuntimeError(
                f"`docker compose up` failed for {project_name}: "
                f"stdout={up.stdout!r} stderr={up.stderr!r}"
            )
        port = _mapped_port(project_name)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)
        return AgentAuthContainer(base_url=base_url, project_name=project_name)

    yield _factory

    for project_name in started:
        down = _compose(project_name, "down", "-v", "--remove-orphans")
        if down.returncode != 0:
            print(
                f"warning: teardown of {project_name} failed: "
                f"stdout={down.stdout!r} stderr={down.stderr!r}"
            )


@pytest.fixture
def agent_auth_container(agent_auth_container_factory) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
