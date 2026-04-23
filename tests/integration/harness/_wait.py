# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Readiness probes for services in a Docker Compose cluster.

Each probe is a callable ``(ServiceHandle) -> (ok, diagnostic)``. The
diagnostic is surfaced in the startup-timeout error message so a flaky
probe shows up as a concrete symptom ("status=502 not in accept_statuses")
rather than an opaque timeout. The :class:`HealthChecks` factory hosts
the common strategies — callers that need bespoke logic can just write
their own callable.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.integration.harness._cluster import ServiceHandle


ServiceWaitFn = Callable[["ServiceHandle"], tuple[bool, str]]
"""Readiness probe: ``(service) -> (is_healthy, diagnostic_message)``.

``ServiceWaitFn`` is polled until it returns ``True`` or the cluster's
start-timeout deadline fires. The diagnostic is only shown on failure,
but cheap-to-compute descriptions make debugging faster.
"""


_DEFAULT_HTTP_TIMEOUT_SECONDS = 2.0
_DEFAULT_SOCKET_TIMEOUT_SECONDS = 0.5


class HealthChecks:
    """Factory for the built-in readiness probes.

    Named to mirror ``docker-compose-rule``'s ``HealthChecks`` class so
    the JUnit references in the rework issue map 1:1 to the Python API.
    """

    @staticmethod
    def to_respond_over_http(
        *,
        internal_port: int,
        url_format: str,
        accept_statuses: Iterable[int] = (200, 204),
        request_timeout_seconds: float = _DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> ServiceWaitFn:
        """Build an HTTP-response probe.

        ``url_format`` is passed through :meth:`DockerPort.in_format`, so
        callers interpolate host / port via ``$HOST`` / ``$EXTERNAL_PORT``.
        Any response whose status code lives in ``accept_statuses`` counts
        as healthy — useful for health endpoints that require a bearer
        token (``401``/``403`` answered unauthenticated is still a
        positive "server is listening" signal).
        """
        statuses = frozenset(accept_statuses)
        if not statuses:
            raise ValueError("accept_statuses must be non-empty")

        def _check(service: ServiceHandle) -> tuple[bool, str]:
            port = service.port(internal_port)
            url = port.in_format(url_format)
            try:
                with urllib.request.urlopen(url, timeout=request_timeout_seconds) as resp:
                    if resp.status in statuses:
                        return True, f"status={resp.status}"
                    return False, (f"status={resp.status} not in {sorted(statuses)} (url={url})")
            except urllib.error.HTTPError as exc:
                if exc.code in statuses:
                    return True, f"status={exc.code}"
                return False, (f"status={exc.code} not in {sorted(statuses)} (url={url})")
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                return False, f"connection error for {url}: {exc!r}"

        return _check

    @staticmethod
    def to_have_ports_open(
        *internal_ports: int,
        connect_timeout_seconds: float = _DEFAULT_SOCKET_TIMEOUT_SECONDS,
    ) -> ServiceWaitFn:
        """Build a TCP-socket probe that succeeds once every listed port accepts a connection.

        Mirrors ``docker-compose-rule``'s ``toHaveAllPortsOpen`` for the
        set of ``internal_port``s the caller cares about. A 500 ms
        connect timeout — matching the JUnit rule — keeps a not-yet-
        listening port from blocking the poll loop.
        """
        if not internal_ports:
            raise ValueError("at least one internal_port is required")
        ports = tuple(internal_ports)

        def _check(service: ServiceHandle) -> tuple[bool, str]:
            for internal_port in ports:
                docker_port = service.port(internal_port)
                try:
                    with socket.create_connection(
                        (docker_port.host, docker_port.external_port),
                        timeout=connect_timeout_seconds,
                    ):
                        pass
                except OSError as exc:
                    return False, (
                        f"internal_port={internal_port} "
                        f"external={docker_port.host}:{docker_port.external_port}: {exc!r}"
                    )
            return True, f"internal_ports={list(ports)} open"

        return _check
