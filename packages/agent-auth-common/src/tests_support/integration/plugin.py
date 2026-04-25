# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared pytest plugin for the Docker-backed integration suites.

Loaded via ``addopts = ["-p", "tests_support.integration.plugin"]`` in
the workspace ``pyproject.toml`` so every package's
``tests/integration/`` tree gets the same session-scoped image build,
docker-availability skip, per-test ``agent-auth`` container factory,
and ``pytest_runtest_makereport`` hook that the per-service conftests
rely on when they request ``save_logs_to(..., on_success=False)``.

Compose lifecycle is handled by :mod:`tests_support.integration.harness`
— a fluent builder over ``docker compose`` (subprocess, no
testcontainers). The session-scoped image build remains a direct
``docker build`` call so each per-service test image is rebuilt once
per pytest run off the working tree.
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
from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

# Heavy production-side imports are gated behind ``TYPE_CHECKING`` so
# the plugin's module-level load (triggered by every pytest
# invocation via ``addopts = ["-p", ...]``) doesn't pull in
# ``agent_auth_client``, ``things_bridge_client``, ``things_models``
# etc. before pytest-cov starts instrumenting. Pulling them in eagerly
# masks dataclass-field coverage in ``things_models.models`` (the
# ``@dataclass`` decorator runs at import time, before tracing starts,
# so coverage sees the lines as cold even though every test that
# imports the model exercises them). Local imports inside fixture
# bodies and methods see the modules under tracing, restoring the
# expected coverage numbers.
if TYPE_CHECKING:
    from agent_auth_client import AgentAuthClient
    from things_bridge_client import ThingsBridgeClient

from tests_support.integration._chmod import (
    make_bind_mount_dir_readable,
    make_bind_mount_file_readable,
)
from tests_support.integration.harness import (
    DockerComposeCluster,
    HealthChecks,
    StartedCluster,
)
from tests_support.integration.support import (
    COMPOSE_FILE,
    DOCKER_DIR,
    PER_SERVICE_DOCKERFILES,
    build_test_image,
    docker_compose_available,
    phase_timer,
    seed_empty_fixtures_dir,
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
        from agent_auth_client import AgentAuthClient

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
    make_bind_mount_dir_readable(config_dir)
    make_bind_mount_file_readable(config_path)


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


# ---------------------------------------------------------------------------
# things-bridge stack fixtures.
# ---------------------------------------------------------------------------
# The bridge's integration tests always spin up the pair (agent-auth +
# things-bridge); the things-cli integration tests reuse the same
# stack so both tree's fixtures live here rather than in a per-service
# conftest.

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
        from things_bridge_client import ThingsBridgeClient

        return ThingsBridgeClient(self.base_url, timeout_seconds=10.0)

    def write_fixture(self, fixture: dict[str, Any]) -> None:
        """Write/replace ``things.yaml`` in the bind-mounted fixtures dir."""
        path = self.fixtures_dir / "things.yaml"
        path.write_text(yaml.safe_dump(fixture))
        make_bind_mount_file_readable(path)

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


def _write_agent_auth_config_for_bridge(
    config_dir: Path,
    *,
    access_token_ttl_seconds: int,
    refresh_token_ttl_seconds: int,
) -> None:
    """Mirror :func:`_write_test_config` for the multi-service bridge stack."""
    with BASELINE_CONFIG.open() as f:
        config = yaml.safe_load(f) or {}
    # Under #6 the notifier runs as a sidecar container; the URL is
    # fixed across tests and the approve/deny variant is chosen by the
    # NOTIFIER_MODE env var passed to docker compose (see
    # APPROVAL_PLUGINS above).
    config["notification_plugin_url"] = "http://notifier:9150/"
    config["access_token_ttl_seconds"] = access_token_ttl_seconds
    config["refresh_token_ttl_seconds"] = refresh_token_ttl_seconds
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    make_bind_mount_dir_readable(config_dir)
    make_bind_mount_file_readable(config_path)


def _things_bridge_cluster(
    *,
    project_name: str,
    image_tags: dict[str, str],
    config_dir: Path,
    fixtures_dir: Path,
    notifier_mode: str,
    logs_dir: Path,
) -> DockerComposeCluster:
    """Build the per-test cluster definition with both service waits wired up."""
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
    """Factory fixture — spin up the agent-auth + things-bridge pair."""
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

        _write_agent_auth_config_for_bridge(
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
        # via the in-container CLI. ``agent-auth`` is reached only over
        # the internal Compose network; no host-port mapping for it is
        # required.
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
