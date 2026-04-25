# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fluent builder for a ``docker compose`` lifecycle under integration tests.

The harness wraps ``docker compose`` directly via ``subprocess`` — there
is no testcontainers dependency. Every action (``config``, ``up``,
``port``, ``exec``, ``logs``, ``down``) maps 1:1 to a CLI invocation
the developer can reproduce by hand, which keeps failures debuggable.

Design properties preserved from ``palantir/docker-compose-rule``:

- **Fluent builder** — configuration is explicit and local to the test
  fixture; no hidden state.
- **Project name on the CLI** — passed via ``--project-name`` rather than
  mutating ``os.environ``'s ``COMPOSE_PROJECT_NAME``.
- **Env via subprocess ``env=``** — configured env vars are handed to
  ``docker compose`` through ``subprocess.run(env=...)`` only. The test
  process's ``os.environ`` is never mutated.
- **Parallel wait with shared deadline** — the first unhealthy service
  fails the whole startup instead of waiting the full timeout on every
  other service serially.
- **Pre-flight ``docker compose config``** — cheap YAML validation so a
  typo surfaces as "bad file" rather than "container exited immediately".
- **Log capture on teardown** — ``save_logs_to(dir, on_success=False)``
  dumps ``docker compose logs`` per service on failure (or always, if
  the caller wants it), giving CI an artefact to upload.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tests_support.integration.harness._port import DockerPort

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Self

    from tests_support.integration.harness._wait import ServiceWaitFn

_log = logging.getLogger("integration.harness")

DEFAULT_START_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_STOP_TIMEOUT_SECONDS = 30.0
DEFAULT_CONFIG_TIMEOUT_SECONDS = 30.0
DEFAULT_UP_TIMEOUT_SECONDS = 300.0
DEFAULT_PORT_LOOKUP_TIMEOUT_SECONDS = 15.0
DEFAULT_LOGS_TIMEOUT_SECONDS = 30.0


class ClusterStartupTimeout(RuntimeError):
    """Raised when one or more services fail every wait probe before the deadline."""


@dataclass(frozen=True)
class _ServiceWait:
    """Binds a ``ServiceWaitFn`` to the service it probes."""

    service: str
    check: ServiceWaitFn
    label: str


@dataclass
class DockerComposeClusterBuilder:
    """Fluent builder for :class:`DockerComposeCluster`.

    Only a builder, not a runtime object — call :meth:`build` to freeze
    the configuration into a :class:`DockerComposeCluster`, then
    :meth:`DockerComposeCluster.start` to launch it. Separating the two
    means the same cluster definition can be inspected by unit tests
    without starting a subprocess.
    """

    _project_name: str | None = None
    _files: list[Path] = field(default_factory=list)
    _env: dict[str, str] = field(default_factory=dict)
    _waits: list[_ServiceWait] = field(default_factory=list)
    _logs_dir: Path | None = None
    _logs_on_success: bool = False
    _start_timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS
    _poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    _stop_timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS

    def project_name(self, name: str) -> Self:
        """Set the ``docker compose --project-name`` value. Required."""
        self._project_name = name
        return self

    def file(self, path: Path | str) -> Self:
        """Add a ``-f <path>`` compose file. At least one is required."""
        self._files.append(Path(path))
        return self

    def env(self, key: str, value: str) -> Self:
        """Add an env var to the ``docker compose`` subprocess. Never touches ``os.environ``."""
        self._env[key] = value
        return self

    def waiting_for_service(
        self, service: str, check: ServiceWaitFn, *, label: str | None = None
    ) -> Self:
        """Register a readiness probe polled until healthy or timeout.

        ``label`` is surfaced in timeout error messages when set — useful
        when the same service has multiple probes and you want to tell
        them apart.
        """
        self._waits.append(_ServiceWait(service=service, check=check, label=label or service))
        return self

    def save_logs_to(self, directory: Path | str, *, on_success: bool = False) -> Self:
        """Persist ``docker compose logs`` per service into ``directory`` on teardown.

        ``on_success=False`` (default) only writes logs when the cluster
        startup failed or the caller passed ``test_failed=True`` to
        :meth:`StartedCluster.stop`. Flip to ``True`` to always capture.
        """
        self._logs_dir = Path(directory)
        self._logs_on_success = on_success
        return self

    def start_timeout_seconds(self, seconds: float) -> Self:
        """Override the cluster-wide wait deadline (default 30 s)."""
        self._start_timeout_seconds = seconds
        return self

    def poll_interval_seconds(self, seconds: float) -> Self:
        """Override the wait-strategy poll interval (default 0.2 s)."""
        self._poll_interval_seconds = seconds
        return self

    def build(self) -> DockerComposeCluster:
        """Freeze builder state into an immutable :class:`DockerComposeCluster`.

        Raises ``ValueError`` on missing required inputs — caught early so
        a typo shows up at fixture-setup time, not inside ``docker compose``.
        """
        if self._project_name is None:
            raise ValueError("DockerComposeClusterBuilder: project_name() is required")
        if not self._files:
            raise ValueError("DockerComposeClusterBuilder: at least one file() is required")
        return DockerComposeCluster(
            project_name=self._project_name,
            files=tuple(self._files),
            env=dict(self._env),
            waits=tuple(self._waits),
            logs_dir=self._logs_dir,
            logs_on_success=self._logs_on_success,
            start_timeout_seconds=self._start_timeout_seconds,
            poll_interval_seconds=self._poll_interval_seconds,
            stop_timeout_seconds=self._stop_timeout_seconds,
        )


@dataclass(frozen=True)
class DockerComposeCluster:
    """Immutable definition of a compose project.

    Build via :meth:`builder`; launch via :meth:`start`.
    """

    project_name: str
    files: tuple[Path, ...]
    env: dict[str, str]
    waits: tuple[_ServiceWait, ...]
    logs_dir: Path | None
    logs_on_success: bool
    start_timeout_seconds: float
    poll_interval_seconds: float
    stop_timeout_seconds: float

    @staticmethod
    def builder() -> DockerComposeClusterBuilder:
        """Return a new :class:`DockerComposeClusterBuilder`."""
        return DockerComposeClusterBuilder()

    def start(self) -> StartedCluster:
        """Validate the compose file, ``up -d``, wait for services, return the handle.

        On any failure before all waits succeed, the partially-started
        project is torn down (and logs are captured if ``save_logs_to``
        is configured) before the exception propagates. That way a
        failed startup never leaves orphan containers behind.
        """
        running = StartedCluster(
            project_name=self.project_name,
            files=self.files,
            env=dict(self.env),
            logs_dir=self.logs_dir,
            logs_on_success=self.logs_on_success,
            stop_timeout_seconds=self.stop_timeout_seconds,
        )
        try:
            running._validate_compose_files()
            running._compose_up()
            if self.waits:
                running._wait_for_all_services(
                    waits=self.waits,
                    deadline_seconds=self.start_timeout_seconds,
                    poll_interval_seconds=self.poll_interval_seconds,
                )
        except BaseException:
            running.stop(test_failed=True)
            raise
        return running


@dataclass
class StartedCluster:
    """Running compose project — ports, exec, teardown.

    Don't instantiate directly — obtained from :meth:`DockerComposeCluster.start`.
    """

    project_name: str
    files: tuple[Path, ...]
    env: dict[str, str]
    logs_dir: Path | None
    logs_on_success: bool
    stop_timeout_seconds: float
    _stopped: bool = field(default=False, init=False, repr=False, compare=False)
    _port_cache: dict[tuple[str, int], DockerPort] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @property
    def compose_file(self) -> Path:
        """Return the first ``-f`` file. Convenience for callers that shell out.

        Compose v2 accepts one ``-f`` from the fixture today; if a future
        test needs to stack multiple files, use :meth:`file_args` instead.
        """
        return self.files[0]

    def file_args(self) -> list[str]:
        """Return ``["-f", path, "-f", path, ...]`` for subprocess arg construction."""
        args: list[str] = []
        for file in self.files:
            args.extend(["-f", str(file)])
        return args

    def service(self, name: str) -> ServiceHandle:
        """Return a handle to ``name`` for port lookup and exec."""
        return ServiceHandle(cluster=self, name=name)

    def resolve_port(self, service: str, internal_port: int) -> DockerPort:
        """Resolve and cache the external mapping for ``service:internal_port``.

        Results are cached for the lifetime of the :class:`StartedCluster`
        because external port assignments don't change after ``up`` — the
        wait loop would otherwise shell out on every poll iteration.
        """
        key = (service, internal_port)
        cached = self._port_cache.get(key)
        if cached is not None:
            return cached
        port = self._lookup_port(service, internal_port)
        self._port_cache[key] = port
        return port

    def exec(
        self,
        service: str,
        argv: Sequence[str],
        *,
        timeout_seconds: float | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``docker compose exec -T <service> <argv>`` and return the result.

        Does not raise on non-zero exit — callers decide how to interpret
        exit codes (negative-path tests sometimes want the failure for
        assertion). ``-T`` disables TTY allocation; required because the
        test runner is not attached to a terminal.
        """
        return subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "exec",
                "-T",
                service,
                *argv,
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            input=input_text,
        )

    def stop_service(self, service: str, *, timeout_seconds: float = 30.0) -> None:
        """Stop a single service without tearing the rest of the project down.

        Used to exercise cross-service failure modes (e.g. the bridge's
        ``authz_unavailable`` path where ``agent-auth`` goes away but
        the bridge keeps serving).
        """
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "stop",
                service,
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker compose stop {service!r} failed for project "
                f"{self.project_name!r}: exit={result.returncode} "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )

    def logs(
        self,
        service: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_LOGS_TIMEOUT_SECONDS,
    ) -> str:
        """Return ``docker compose logs`` output. All services when ``service is None``."""
        cmd = [
            "docker",
            "compose",
            *self.file_args(),
            "--project-name",
            self.project_name,
            "logs",
            "--no-color",
        ]
        if service is not None:
            cmd.append(service)
        result = subprocess.run(
            cmd,
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return result.stdout

    def list_services(self) -> list[str]:
        """Return service names defined in the compose files (via ``config --services``)."""
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "config",
                "--services",
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_CONFIG_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def stop(self, *, test_failed: bool = False) -> None:
        """Tear the project down (``down -v --remove-orphans``). Idempotent.

        Captures ``docker compose logs`` into ``logs_dir`` BEFORE running
        ``down`` so the container logs still exist. When ``test_failed``
        is ``True`` or the caller opted into ``on_success=True``, per-
        service logs are written under ``logs_dir``.
        """
        if self._stopped:
            return
        self._stopped = True
        if self.logs_dir is not None and (test_failed or self.logs_on_success):
            self._save_logs()
        self._compose_down()

    # --- subprocess helpers -------------------------------------------------

    def _subprocess_env(self) -> dict[str, str]:
        """Build the env for ``docker compose`` — inherited PATH/DOCKER_* plus our overrides.

        Never mutates ``os.environ``.
        """
        merged = dict(os.environ)
        merged.update(self.env)
        return merged

    def _validate_compose_files(self) -> None:
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "config",
                "--quiet",
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_CONFIG_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker compose config failed for project {self.project_name!r}: "
                f"exit={result.returncode} stdout={result.stdout!r} "
                f"stderr={result.stderr!r}"
            )

    def _compose_up(self) -> None:
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "up",
                "-d",
                "--remove-orphans",
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_UP_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker compose up failed for project {self.project_name!r}: "
                f"exit={result.returncode} stdout={result.stdout!r} "
                f"stderr={result.stderr!r}"
            )

    def _compose_down(self) -> None:
        # Defensive: docker compose down -t takes an int (seconds).
        down_timeout = int(self.stop_timeout_seconds)
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "down",
                "-v",
                "--remove-orphans",
                "-t",
                str(down_timeout),
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(60.0, self.stop_timeout_seconds + 30.0),
        )
        if result.returncode != 0:
            # Log rather than raise — teardown must be best-effort so a
            # failing-down doesn't mask the test's original failure.
            _log.warning(
                "docker compose down failed for project %r: exit=%d stdout=%r stderr=%r",
                self.project_name,
                result.returncode,
                result.stdout,
                result.stderr,
            )

    def _save_logs(self) -> None:
        assert self.logs_dir is not None
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        services = self.list_services()
        if not services:
            # Fall back to a single combined dump so we at least leave
            # *something* behind when ``config --services`` fails (e.g.
            # the compose file no longer parses).
            combined = self.logs()
            (self.logs_dir / "combined.log").write_text(combined)
            return
        for service in services:
            output = self.logs(service)
            (self.logs_dir / f"{service}.log").write_text(output)

    def _lookup_port(self, service: str, internal_port: int) -> DockerPort:
        result = subprocess.run(
            [
                "docker",
                "compose",
                *self.file_args(),
                "--project-name",
                self.project_name,
                "port",
                service,
                str(internal_port),
            ],
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_PORT_LOOKUP_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"could not resolve external port for service {service!r} "
                f"internal_port={internal_port} in project "
                f"{self.project_name!r}: exit={result.returncode} "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        # docker compose port prints one "host:port" line per published
        # mapping; our fixtures bind each port once, so take the first
        # line and parse from the right to handle IPv6-bracketed hosts.
        first_line = result.stdout.strip().splitlines()[0].strip()
        host, sep, port_str = first_line.rpartition(":")
        if not sep or not port_str.isdigit() or not host:
            raise RuntimeError(
                f"could not parse docker compose port output {first_line!r} "
                f"for service {service!r} internal_port={internal_port}"
            )
        return DockerPort(
            host=host,
            external_port=int(port_str),
            internal_port=internal_port,
        )

    def _wait_for_all_services(
        self,
        *,
        waits: tuple[_ServiceWait, ...],
        deadline_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        deadline = time.monotonic() + deadline_seconds
        # max_workers must be >=1 even if waits is somehow empty; build
        # guards that upstream but we keep the clamp defensive here.
        worker_count = max(1, len(waits))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(self._poll_service, wait, deadline, poll_interval_seconds): wait
                for wait in waits
            }
            for fut in as_completed(futures):
                ok, diagnostic = fut.result()
                wait = futures[fut]
                if not ok:
                    raise ClusterStartupTimeout(
                        f"service {wait.service!r} ({wait.label}) not healthy "
                        f"within {deadline_seconds}s: {diagnostic}"
                    )

    def _poll_service(
        self,
        wait: _ServiceWait,
        deadline: float,
        poll_interval_seconds: float,
    ) -> tuple[bool, str]:
        last_diagnostic = "no attempts recorded"
        while True:
            try:
                ok, diagnostic = wait.check(self.service(wait.service))
                last_diagnostic = diagnostic
                if ok:
                    return True, diagnostic
            except Exception as exc:
                last_diagnostic = f"probe raised: {exc!r}"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, last_diagnostic
            time.sleep(min(poll_interval_seconds, remaining))


@dataclass(frozen=True)
class ServiceHandle:
    """View of one service inside a :class:`StartedCluster`.

    Lightweight — created on demand by ``StartedCluster.service(name)``.
    Actual port lookup + caching lives on the cluster so repeated
    ``service("x").port(9100)`` calls share the cache.
    """

    cluster: StartedCluster
    name: str

    def port(self, internal_port: int) -> DockerPort:
        """Return the external :class:`DockerPort` mapped to ``internal_port``."""
        return self.cluster.resolve_port(self.name, internal_port)
