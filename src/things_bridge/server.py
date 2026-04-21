# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP server exposing read-only Things operations."""

import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config
from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_models.client import ThingsClient

READ_SCOPE = "things:read"
HEALTH_SCOPE = "things-bridge:health"

# Upper bound on ids accepted from URL paths. Things ids are short; reject
# anything excessive before it ever reaches AppleScript.
_MAX_ID_LEN = 128


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

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        params = parse_qs(url.query)

        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        # Health is authenticated under ``things-bridge:health`` to mirror
        # ``agent-auth/health``. Readiness probes that need to keep working
        # without a token can probe the 401 (server-is-up signal); the
        # 200 path requires the scope. Health remains unversioned by convention.
        if path == "/things-bridge/health":
            if not self._validate(token, HEALTH_SCOPE, "things-bridge health check"):
                return
            self._send_json(200, {"status": "ok"})
            return

        things: ThingsClient = self._bridge.things

        # Routing: longest-prefix specific paths first.
        if path == "/things-bridge/v1/todos":
            if not self._validate(token, READ_SCOPE, "List Things todos"):
                return
            try:
                todos = things.list_todos(
                    list_id=_first(params, "list"),
                    project_id=_first(params, "project"),
                    area_id=_first(params, "area"),
                    tag=_first(params, "tag"),
                    status=_first(params, "status"),
                )
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"todos": [t.to_json() for t in todos]})
            return

        if path.startswith("/things-bridge/v1/todos/"):
            todo_id = _safe_id(path[len("/things-bridge/v1/todos/") :])
            if todo_id is None:
                self._send_json(404, {"error": "not_found"})
                return
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
            if not self._validate(token, READ_SCOPE, "List Things projects"):
                return
            try:
                projects = things.list_projects(area_id=_first(params, "area"))
            except ThingsError as exc:
                self._send_things_error_response(exc)
                return
            self._send_json(200, {"projects": [p.to_json() for p in projects]})
            return

        if path.startswith("/things-bridge/v1/projects/"):
            project_id = _safe_id(path[len("/things-bridge/v1/projects/") :])
            if project_id is None:
                self._send_json(404, {"error": "not_found"})
                return
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
            area_id = _safe_id(path[len("/things-bridge/v1/areas/") :])
            if area_id is None:
                self._send_json(404, {"error": "not_found"})
                return
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


class ThingsBridgeServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for things-bridge."""

    # Non-daemon request threads combined with ``block_on_close=True``
    # (inherited default from ``ThreadingMixIn``) let ``server_close``
    # wait for in-flight requests to complete during graceful shutdown.
    # The shutdown watchdog in ``run_server`` bounds the wait.
    daemon_threads = False

    def __init__(self, config: Config, things: ThingsClient, authz: AgentAuthClient):
        self.config = config
        self.things = things
        self.authz = authz
        super().__init__((config.host, config.port), ThingsBridgeHandler)


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
    server = ThingsBridgeServer(config, things, authz)
    drain_complete = _install_shutdown_handler(server, config.shutdown_deadline_seconds)
    print(f"things-bridge listening on {config.host}:{config.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        try:
            server.server_close()
        finally:
            drain_complete.set()
