"""HTTP server exposing read-only Things operations."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from things_bridge.authz import AuthzClient
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
from things_bridge.things import ThingsClient

READ_SCOPE = "things:read"


class ThingsBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for things-bridge read-only endpoints."""

    @property
    def _bridge(self) -> "ThingsBridgeServer":
        return self.server  # type: ignore[return-value]

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 — match BaseHTTPRequestHandler
        # Never log bearer tokens; suppress the default access log entirely.
        pass

    def _extract_bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return header[7:].strip() or None

    def _validate(self, token: str, description: str) -> bool:
        """Delegate token validation to agent-auth; returns True on success.

        On failure writes the HTTP response and returns False.
        """
        try:
            self._bridge.authz.validate(token, READ_SCOPE, description=description)
        except AuthzTokenExpiredError:
            self._send_json(401, {"error": "token_expired"})
            return False
        except AuthzTokenInvalidError:
            self._send_json(401, {"error": "unauthorized"})
            return False
        except AuthzScopeDeniedError:
            self._send_json(403, {"error": "scope_denied"})
            return False
        except AuthzUnavailableError as exc:
            self._send_json(502, {"error": "authz_unavailable", "detail": str(exc)})
            return False
        return True

    def _things_error_response(self, exc: ThingsError) -> None:
        if isinstance(exc, ThingsNotFoundError):
            self._send_json(404, {"error": "not_found", "detail": str(exc)})
            return
        if isinstance(exc, ThingsPermissionError):
            self._send_json(
                503,
                {"error": "things_permission_denied", "detail": str(exc)},
            )
            return
        self._send_json(502, {"error": "things_unavailable", "detail": str(exc)})

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        url = urlsplit(self.path)
        path = url.path
        params = parse_qs(url.query)

        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        things: ThingsClient = self._bridge.things

        # Routing: longest-prefix specific paths first.
        if path == "/things-bridge/todos":
            if not self._validate(token, "List Things todos"):
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
                self._things_error_response(exc)
                return
            self._send_json(200, {"todos": [t.to_json() for t in todos]})
            return

        if path.startswith("/things-bridge/todos/"):
            todo_id = path[len("/things-bridge/todos/"):]
            if not todo_id or "/" in todo_id:
                self._send_json(404, {"error": "not_found"})
                return
            if not self._validate(token, f"Read Things todo {todo_id}"):
                return
            try:
                todo = things.get_todo(todo_id)
            except ThingsError as exc:
                self._things_error_response(exc)
                return
            self._send_json(200, {"todo": todo.to_json()})
            return

        if path == "/things-bridge/projects":
            if not self._validate(token, "List Things projects"):
                return
            try:
                projects = things.list_projects(area_id=_first(params, "area"))
            except ThingsError as exc:
                self._things_error_response(exc)
                return
            self._send_json(200, {"projects": [p.to_json() for p in projects]})
            return

        if path.startswith("/things-bridge/projects/"):
            project_id = path[len("/things-bridge/projects/"):]
            if not project_id or "/" in project_id:
                self._send_json(404, {"error": "not_found"})
                return
            if not self._validate(token, f"Read Things project {project_id}"):
                return
            try:
                project = things.get_project(project_id)
            except ThingsError as exc:
                self._things_error_response(exc)
                return
            self._send_json(200, {"project": project.to_json()})
            return

        if path == "/things-bridge/areas":
            if not self._validate(token, "List Things areas"):
                return
            try:
                areas = things.list_areas()
            except ThingsError as exc:
                self._things_error_response(exc)
                return
            self._send_json(200, {"areas": [a.to_json() for a in areas]})
            return

        if path.startswith("/things-bridge/areas/"):
            area_id = path[len("/things-bridge/areas/"):]
            if not area_id or "/" in area_id:
                self._send_json(404, {"error": "not_found"})
                return
            if not self._validate(token, f"Read Things area {area_id}"):
                return
            try:
                area = things.get_area(area_id)
            except ThingsError as exc:
                self._things_error_response(exc)
                return
            self._send_json(200, {"area": area.to_json()})
            return

        self._send_json(404, {"error": "not_found"})


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0] or None


class ThingsBridgeServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for things-bridge."""

    def __init__(self, config: Config, things: ThingsClient, authz: AuthzClient):
        self.config = config
        self.things = things
        self.authz = authz
        super().__init__((config.host, config.port), ThingsBridgeHandler)


def run_server(config: Config, things: ThingsClient, authz: AuthzClient) -> None:
    """Start the things-bridge HTTP server."""
    server = ThingsBridgeServer(config, things, authz)
    print(f"things-bridge listening on {config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
