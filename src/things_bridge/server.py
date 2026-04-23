# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP server exposing read-only Things operations."""

import json
import os
import shutil
import signal
import ssl
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from agent_auth_client import (
    AgentAuthClient,
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)
from server_metrics import (
    PROMETHEUS_CONTENT_TYPE,
    Registry,
    render_prometheus_text,
)
from things_bridge.config import Config
from things_bridge.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_bridge.metrics import ThingsBridgeMetrics, build_registry
from things_models.client import ThingsClient
from things_models.models import AreaId, ProjectId, TodoId

READ_SCOPE = "things:read"
HEALTH_SCOPE = "things-bridge:health"
METRICS_SCOPE = "things-bridge:metrics"

# Sentinel route label for unmatched paths; bounds label cardinality
# when a scraper hits arbitrary URLs.
_UNKNOWN_ROUTE = "/unknown"

# Upper bound on ids accepted from URL paths. Things ids are short; reject
# anything excessive before it ever reaches AppleScript.
_MAX_ID_LEN = 128

# How long a successful ``shutil.which`` resolution of the things-client
# executable is trusted by the /health probe. Long enough that a probe
# storm pays at most one PATH walk per window, short enough that a fresh
# install is picked up on the next probe after that window.
_HEALTH_THINGS_CLIENT_CACHE_TTL_SECONDS = 30.0


class _HealthChecker:
    """Evaluate the things-bridge's critical dependencies for /health.

    Currently verifies that ``things_client_command[0]`` resolves to an
    executable — either via PATH lookup (bare name) or as an absolute
    path. ``auth_url`` reachability is *not* re-probed here: the /health
    handler already round-trips through ``AgentAuthClient.validate`` to
    authorise the probe token, and that call raises
    ``AuthzUnavailableError`` → 502 if agent-auth is down. Adding a
    second ping would only duplicate that signal.

    The result is cached for ``_HEALTH_THINGS_CLIENT_CACHE_TTL_SECONDS``
    so a high-frequency probe cadence doesn't turn into a stream of
    filesystem walks.
    """

    def __init__(
        self,
        things_client_command: list[str],
        *,
        cache_ttl_seconds: float = _HEALTH_THINGS_CLIENT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        resolver: Callable[[str], str | None] = shutil.which,
    ):
        if not things_client_command:
            raise ValueError("_HealthChecker: things_client_command must not be empty")
        self._executable = things_client_command[0]
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._resolver = resolver
        self._cached_at: float | None = None
        self._cached_resolvable: bool = False

    def things_client_resolvable(self) -> bool:
        """Return True iff ``things_client_command[0]`` currently resolves.

        Cached for ``cache_ttl_seconds``; first call always queries.
        """
        now = self._clock()
        if self._cached_at is not None and now - self._cached_at < self._cache_ttl_seconds:
            return self._cached_resolvable
        self._cached_resolvable = self._resolver(self._executable) is not None
        self._cached_at = now
        return self._cached_resolvable


def _safe_id(raw: str | None) -> str | None:
    """Reject ids that don't match the allow-list of safe characters.

    Returns the id unchanged if safe, ``None`` otherwise. Used before building
    audit/JIT description strings and before passing to ThingsApplescriptClient.
    Only printable ASCII (excluding ``/``) and non-ASCII characters above U+007F
    are permitted.
    """
    if raw is None or not raw or len(raw) > _MAX_ID_LEN:
        return None
    for ch in raw:
        cp = ord(ch)
        # Allow printable ASCII (0x20-0x7E) except slash, plus non-ASCII (>0x7F).
        if cp > 0x7F:
            continue
        if cp < 0x20 or cp == 0x7F or ch == "/":
            return None
    return raw


class ThingsBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for things-bridge endpoints."""

    @property
    def _bridge(self) -> "ThingsBridgeServer":
        return self.server  # type: ignore[return-value]

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # Suppress the default access log — request paths can reveal
        # Things ids and our bearer tokens appear in headers. Errors
        # still surface via the default ``log_error`` implementation.
        pass

    def _extract_bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return header[7:].strip() or None

    def _validate(self, token: str, scope: str, description: str) -> bool:
        """Delegate token validation to agent-auth.

        ``scope`` is a required positional so every call site states its
        intent explicitly — silently defaulting to a single scope makes
        it easy to forget the override when adding a new endpoint.

        Returns ``True`` when ``authz.validate()`` completes without raising.
        On failure writes the error HTTP response and returns ``False``.
        """
        try:
            self._bridge.authz.validate(token, scope, description=description)
            return True
        except AuthzTokenExpiredError:
            self._send_json(401, {"error": "token_expired"})
        except AuthzTokenInvalidError:
            self._send_json(401, {"error": "unauthorized"})
        except AuthzScopeDeniedError:
            self._send_json(403, {"error": "scope_denied"})
        except AuthzRateLimitedError as exc:
            # Passthrough the upstream Retry-After so clients pace
            # themselves against agent-auth's bucket, not the bridge's.
            body = json.dumps({"error": "rate_limited"}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", str(exc.retry_after_seconds))
            self.end_headers()
            self.wfile.write(body)
        except AuthzUnavailableError:
            self._send_json(502, {"error": "authz_unavailable"})
        return False

    def _send_things_error_response(self, exc: ThingsError) -> None:
        # Do not include ``str(exc)`` in the response body: AppleScript /
        # osascript stderr can contain local filesystem paths, usernames, and
        # excerpts of the executed script — that would be a host-info leak.
        if isinstance(exc, ThingsNotFoundError):
            self._send_json(404, {"error": "not_found"})
            return
        if isinstance(exc, ThingsPermissionError):
            self._send_json(503, {"error": "things_permission_denied"})
            return
        self._send_json(502, {"error": "things_unavailable"})

    def send_response(self, code: int, message: str | None = None) -> None:
        # Capture the status code so ``do_GET`` can label the request
        # duration histogram. ``BaseHTTPRequestHandler`` accepts either
        # an ``HTTPStatus`` or a bare int; normalise here.
        self._last_status_code = int(code)
        super().send_response(code, message)

    def _handle_metrics(self) -> None:
        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return
        if not self._validate(token, METRICS_SCOPE, "things-bridge metrics scrape"):
            return
        registry: Registry = self._bridge.registry
        body = render_prometheus_text(registry).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", PROMETHEUS_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        metrics = self._bridge.metrics
        metrics.http_active_requests.inc(method="GET")
        start = time.perf_counter()
        # ``_route_template`` is set by ``_dispatch_get`` before it hands
        # off to a handler; default preserves _UNKNOWN_ROUTE if the
        # dispatcher returns without matching.
        self._route_template = _UNKNOWN_ROUTE
        try:
            self._dispatch_get()
        finally:
            duration = time.perf_counter() - start
            metrics.http_active_requests.dec(method="GET")
            status_code = str(getattr(self, "_last_status_code", 0))
            metrics.http_request_duration.observe(
                duration,
                method="GET",
                route=self._route_template,
                status_code=status_code,
            )

    def _dispatch_get(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        params = parse_qs(url.query)

        token = self._extract_bearer()
        if token is None:
            # Unauthenticated probe: no route resolution is possible
            # without leaking whether the path is known. Label as
            # unknown to keep label cardinality bounded against
            # scanners.
            self._send_json(401, {"error": "unauthorized"})
            return

        # Health is authenticated under ``things-bridge:health`` to mirror
        # ``agent-auth/health``. Readiness probes that need to keep working
        # without a token can probe the 401 (server-is-up signal); the
        # 200 path requires the scope. Health remains unversioned by convention.
        if path == "/things-bridge/health":
            self._route_template = path
            if not self._validate(token, HEALTH_SCOPE, "things-bridge health check"):
                return
            if not self._bridge.health_checker.things_client_resolvable():
                self._send_json(503, {"status": "unhealthy"})
                return
            self._send_json(200, {"status": "ok"})
            return

        if path == "/things-bridge/metrics":
            self._route_template = path
            self._handle_metrics()
            return

        things: ThingsClient = self._bridge.things

        # Routing: longest-prefix specific paths first.
        if path == "/things-bridge/v1/todos":
            self._route_template = path
            if not self._validate(token, READ_SCOPE, "List Things todos"):
                return
            project_filter = _first(params, "project")
            area_filter = _first(params, "area")
            try:
                todos = things.list_todos(
                    list_id=_first(params, "list"),
                    project_id=ProjectId(project_filter) if project_filter is not None else None,
                    area_id=AreaId(area_filter) if area_filter is not None else None,
                    tag=_first(params, "tag"),
                    status=_first(params, "status"),
                )
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"todos": [t.to_json() for t in todos]})
            return

        if path.startswith("/things-bridge/v1/todos/"):
            self._route_template = "/things-bridge/v1/todos/{id}"
            safe_todo_id = _safe_id(path[len("/things-bridge/v1/todos/") :])
            if safe_todo_id is None:
                self._send_json(404, {"error": "not_found"})
                return
            todo_id = TodoId(safe_todo_id)
            if not self._validate(token, READ_SCOPE, f"Read Things todo {todo_id}"):
                return
            try:
                todo = things.get_todo(todo_id)
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"todo": todo.to_json()})
            return

        if path == "/things-bridge/v1/projects":
            self._route_template = path
            if not self._validate(token, READ_SCOPE, "List Things projects"):
                return
            project_area_filter = _first(params, "area")
            try:
                projects = things.list_projects(
                    area_id=AreaId(project_area_filter)
                    if project_area_filter is not None
                    else None,
                )
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"projects": [p.to_json() for p in projects]})
            return

        if path.startswith("/things-bridge/v1/projects/"):
            self._route_template = "/things-bridge/v1/projects/{id}"
            safe_project_id = _safe_id(path[len("/things-bridge/v1/projects/") :])
            if safe_project_id is None:
                self._send_json(404, {"error": "not_found"})
                return
            project_id = ProjectId(safe_project_id)
            if not self._validate(token, READ_SCOPE, f"Read Things project {project_id}"):
                return
            try:
                project = things.get_project(project_id)
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"project": project.to_json()})
            return

        if path == "/things-bridge/v1/areas":
            self._route_template = path
            if not self._validate(token, READ_SCOPE, "List Things areas"):
                return
            try:
                areas = things.list_areas()
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"areas": [a.to_json() for a in areas]})
            return

        if path.startswith("/things-bridge/v1/areas/"):
            self._route_template = "/things-bridge/v1/areas/{id}"
            safe_area_id = _safe_id(path[len("/things-bridge/v1/areas/") :])
            if safe_area_id is None:
                self._send_json(404, {"error": "not_found"})
                return
            area_id = AreaId(safe_area_id)
            if not self._validate(token, READ_SCOPE, f"Read Things area {area_id}"):
                return
            try:
                area = things.get_area(area_id)
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"area": area.to_json()})
            return

        self._send_json(404, {"error": "not_found"})

    def _method_not_allowed(self) -> None:
        # Other methods still participate in metrics. Set the sentinel
        # route template so do_GET's wrapper isn't the only accounting
        # path. (Method labels disambiguate POST /path from GET /path.)
        self._route_template = _UNKNOWN_ROUTE
        self.send_response(405)
        self.send_header("Allow", "GET")
        body = json.dumps({"error": "method_not_allowed"}).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_HEAD = _method_not_allowed
    do_OPTIONS = _method_not_allowed


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0] or None


def _build_tls_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """Build a server-side ``SSLContext`` loaded from PEM files.

    Matches the floor pinned for ``agent-auth`` (``TLSv1_2`` minimum,
    server-role context) so the two services don't drift.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


class ThingsBridgeServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for things-bridge."""

    # Non-daemon request threads combined with ``block_on_close=True``
    # (inherited default from ``ThreadingMixIn``) let ``server_close``
    # wait for in-flight requests to complete during graceful shutdown.
    # The shutdown watchdog in ``run_server`` bounds the wait.
    daemon_threads = False

    def __init__(
        self,
        config: Config,
        things: ThingsClient,
        authz: AgentAuthClient,
        registry: Registry,
        metrics: ThingsBridgeMetrics,
        health_checker: _HealthChecker | None = None,
    ):
        self.config = config
        self.things = things
        self.authz = authz
        self.registry = registry
        self.metrics = metrics
        # Default health checker reads from ``config.things_client_command``;
        # tests can inject a pre-built checker with a stubbed resolver /
        # clock to drive the failure path without mutating PATH.
        self.health_checker = health_checker or _HealthChecker(config.things_client_command)
        super().__init__((config.host, config.port), ThingsBridgeHandler)
        if config.tls_enabled:
            # Wrap the bound listening socket in a TLS context so every
            # accepted connection speaks TLS. See agent-auth's server
            # for the matching pattern and ADR 0025 for rationale.
            self.socket = _build_tls_context(config.tls_cert_path, config.tls_key_path).wrap_socket(
                self.socket, server_side=True
            )


def _install_shutdown_handler(
    server: ThreadingHTTPServer,
    deadline_seconds: float,
    service_name: str = "things-bridge",
) -> threading.Event:
    """Install SIGTERM / SIGINT handlers that bound the full shutdown.

    On first signal, spawns two daemon threads: one calls
    ``server.shutdown()`` to kick ``serve_forever`` out of its loop
    (this must not run on the ``serve_forever`` thread or the call
    deadlocks), and a watchdog that ``os._exit(1)``s if
    ``deadline_seconds`` elapses without the returned ``drain_complete``
    event being set.

    The caller is responsible for setting ``drain_complete`` once
    *every* post-shutdown cleanup step has returned —
    ``server.server_close()`` (which with non-daemon request threads
    blocks on ``_threads.join_all``) and any resource close. The
    watchdog therefore spans the full drain, not just the
    ``serve_forever`` unwind: a request handler hung inside
    ``server_close`` cannot hold the process past its container's
    ``stop_grace_period``.
    """
    shutdown_started = threading.Event()
    drain_complete = threading.Event()

    def _watchdog() -> None:
        if drain_complete.wait(timeout=deadline_seconds):
            return
        print(
            f"{service_name}: shutdown deadline of {deadline_seconds}s exceeded, force-exiting",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)

    def _handle(_signum: int, _frame: object) -> None:
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        threading.Thread(target=_watchdog, daemon=True).start()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    return drain_complete


def run_server(config: Config, things: ThingsClient, authz: AgentAuthClient) -> None:
    """Start the things-bridge HTTP server.

    Registers SIGTERM and SIGINT handlers that drain in-flight requests
    within ``config.shutdown_deadline_seconds`` before returning.
    """
    registry, metrics = build_registry()
    server = ThingsBridgeServer(config, things, authz, registry, metrics)
    drain_complete = _install_shutdown_handler(server, config.shutdown_deadline_seconds)
    # Read the bound port from ``server_address`` (populated during
    # ``server_bind``) so a ``port: 0`` config surfaces the real port.
    bound_port = server.server_address[1]
    scheme = "https" if config.tls_enabled else "http"
    print(f"things-bridge listening on {scheme}://{config.host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        try:
            server.server_close()
        finally:
            drain_complete.set()
