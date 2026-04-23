# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Docker-backed fixtures for agent-auth integration tests.

Each test that requests the fixture gets a fresh Compose project (named
by a per-test UUID), giving it an isolated container, ephemeral host
port, and filesystem. The test talks to the mapped loopback port and
drives state through the agent-auth HTTP API + the ``agent-auth`` CLI
running inside the container.

Compose lifecycle is handled by :mod:`tests.integration.harness` — a
fluent builder over ``docker compose`` (subprocess, no testcontainers).
The session-scoped image build remains a direct ``docker build`` call so
each per-service test image is rebuilt once per pytest run off the
working tree.
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

from agent_auth_client import AgentAuthClient
from tests.integration._support import (
    COMPOSE_FILE,
    DOCKER_DIR,
    PER_SERVICE_DOCKERFILES,
    build_test_image,
    docker_compose_available,
    phase_timer,
    seed_empty_fixtures_dir,
)
from tests.integration.harness import (
    DockerComposeCluster,
    HealthChecks,
    StartedCluster,
)

# The integration runner enables ``log_cli_level=INFO`` so the
# ``integration.timing`` phase logs stream live. The HTTP / docker
# plumbing libraries log at INFO too, which drowns the phase rows
# under noise unrelated to timing. Raise their floors to WARNING so
# the CI log stays grep-friendly. Done unconditionally because this
# module is only imported when the integration suite runs.
for _noisy_logger in ("docker", "urllib3", "asyncio"):
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

AGENT_AUTH_INTERNAL_PORT = 9100


@dataclass
class AgentAuthContainer:
    """Handle for a running agent-auth integration-test container.

    ``cluster`` is the started compose cluster the ``agent-auth`` service
    belongs to. The external port is resolved lazily via the harness's
    :class:`DockerPort` accessor so base_url construction never hand-rolls
    a URL string.
    """

    base_url: str
    cluster: StartedCluster
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
        result = self.cluster.exec(self.service, ["agent-auth", *args])
        if result.returncode != 0:
            raise RuntimeError(
                f"`agent-auth {' '.join(args)}` failed: "
                f"exit={result.returncode} stdout={result.stdout!r} "
                f"stderr={result.stderr!r}"
            )
        return result.stdout

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


def _compose_image_env(image_tags: dict[str, str]) -> dict[str, str]:
    """Return the per-service image env vars the shared compose file reads.

    Centralised so the agent-auth-only and bridge fixtures pass the
    same keys — the compose file rejects a run that leaves a ``${VAR}``
    unresolved.
    """
    return {
        "AGENT_AUTH_TEST_IMAGE": image_tags["agent-auth"],
        "THINGS_BRIDGE_TEST_IMAGE": image_tags["things-bridge"],
        "THINGS_CLI_TEST_IMAGE": image_tags["things-cli"],
    }


def _agent_auth_cluster(
    *,
    project_name: str,
    image_tags: dict[str, str],
    config_dir: Path,
    fixtures_dir: Path,
    notifier_mode: str,
    logs_dir: Path,
) -> DockerComposeCluster:
    """Build the per-test cluster definition for agent-auth integration tests.

    Factored out so the bridge fixture (which uses the same compose file
    but waits for ``things-bridge`` too) can extend it without copying
    the env-var wiring.
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
        .save_logs_to(logs_dir, on_success=False)
        .build()
    )


def _test_failed(request: pytest.FixtureRequest) -> bool:
    """Return True if the pytest node that requested the fixture failed.

    Relies on the ``makereport`` hook in this conftest setting
    ``rep_setup`` / ``rep_call`` attributes on the test item. A missing
    attribute means the test never reached the call phase (collection
    failure or setup-time error), which we conservatively treat as a
    failure so logs are still captured.
    """
    setup = getattr(request.node, "rep_setup", None)
    call = getattr(request.node, "rep_call", None)
    if setup is not None and setup.failed:
        return True
    if call is None:
        return True
    return bool(call.failed)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Expose the per-phase report on the item so fixtures can branch on test failure.

    Required for ``save_logs_to(..., on_success=False)`` to see whether
    the test passed or failed before teardown triggers log capture.
    """
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture
def agent_auth_container_factory(
    _test_image_tags: dict[str, str],
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Generator[Callable[..., AgentAuthContainer], None, None]:
    """Factory fixture — spin up an agent-auth container with custom config.

    Each invocation starts a fresh Compose project. Teardown is registered
    on the fixture so every cluster is stopped at the end of the test.
    Per-service ``docker compose logs`` are dumped into a tmpdir on
    failure for CI to upload.
    """
    started: list[StartedCluster] = []

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
        # container alongside agent-auth, so we still need a fixtures
        # dir even when this test never drives the bridge.
        bridge_fixtures_dir = tmp_path_factory.mktemp(f"tb-fix-{project_name}")
        seed_empty_fixtures_dir(bridge_fixtures_dir)

        logs_dir = tmp_path_factory.mktemp(f"logs-{project_name}")
        cluster = _agent_auth_cluster(
            project_name=project_name,
            image_tags=_test_image_tags,
            config_dir=config_dir,
            fixtures_dir=bridge_fixtures_dir,
            notifier_mode=APPROVAL_PLUGINS[approval],
            logs_dir=logs_dir,
        )
        with phase_timer("compose_start", project=project_name, service="agent-auth"):
            running = cluster.start()
        started.append(running)

        port = running.service("agent-auth").port(AGENT_AUTH_INTERNAL_PORT)
        base_url = port.in_format("http://$HOST:$EXTERNAL_PORT")
        return AgentAuthContainer(base_url=base_url, cluster=running)

    yield _factory

    failed = _test_failed(request)
    for running in started:
        try:
            with phase_timer("compose_stop", project=running.project_name, service="agent-auth"):
                running.stop(test_failed=failed)
        except Exception as e:
            print(f"warning: compose teardown failed: {e!r}")


@pytest.fixture
def agent_auth_container(
    agent_auth_container_factory: Callable[..., AgentAuthContainer],
) -> AgentAuthContainer:
    """Default integration fixture — deny-by-default plugin, stock TTLs."""
    return agent_auth_container_factory()
