"""Integration tests for the things-bridge HTTP server."""

import json
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field

import pytest

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
from things_bridge.models import Area, Project, Todo
from things_bridge.server import ThingsBridgeServer


@dataclass
class FakeAuthz:
    raise_on_validate: Exception | None = None
    last_token: str | None = None
    last_scope: str | None = None
    last_description: str | None = None

    def validate(self, token, required_scope, *, description=None):
        self.last_token = token
        self.last_scope = required_scope
        self.last_description = description
        if self.raise_on_validate is not None:
            raise self.raise_on_validate


@dataclass
class FakeThings:
    todos: list[Todo] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    todos_by_id: dict = field(default_factory=dict)
    projects_by_id: dict = field(default_factory=dict)
    areas_by_id: dict = field(default_factory=dict)
    raise_on_call: Exception | None = None
    last_list_todos_kwargs: dict | None = None

    def list_todos(self, **kwargs):
        self.last_list_todos_kwargs = kwargs
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return list(self.todos)

    def get_todo(self, todo_id):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if todo_id not in self.todos_by_id:
            raise ThingsNotFoundError(todo_id)
        return self.todos_by_id[todo_id]

    def list_projects(self, *, area_id=None):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return list(self.projects)

    def get_project(self, project_id):
        if project_id not in self.projects_by_id:
            raise ThingsNotFoundError(project_id)
        return self.projects_by_id[project_id]

    def list_areas(self):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return list(self.areas)

    def get_area(self, area_id):
        if area_id not in self.areas_by_id:
            raise ThingsNotFoundError(area_id)
        return self.areas_by_id[area_id]


@pytest.fixture
def bridge():
    config = Config(config_dir="/tmp/things-bridge-test", host="127.0.0.1", port=0)
    authz = FakeAuthz()
    things = FakeThings()
    server = ThingsBridgeServer(config, things, authz)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "url": f"http://127.0.0.1:{port}",
            "authz": authz,
            "things": things,
            "server": server,
        }
    finally:
        server.shutdown()


def _get(url: str, token: str | None = "aa_test_token"):
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"_raw": body.decode("utf-8", errors="replace")}
        return exc.code, parsed


def _todo(**overrides):
    defaults = dict(
        id="t1", name="Buy milk", notes="", status="open",
        project_id=None, project_name=None,
        area_id=None, area_name=None,
        tag_names=[],
        due_date=None, activation_date=None,
        completion_date=None, cancellation_date=None,
        creation_date=None, modification_date=None,
    )
    defaults.update(overrides)
    return Todo(**defaults)


def _project(**overrides):
    defaults = dict(
        id="p1", name="Q2 Plan", notes="", status="open",
        area_id=None, area_name=None, tag_names=[],
        due_date=None, activation_date=None,
        completion_date=None, cancellation_date=None,
        creation_date=None, modification_date=None,
    )
    defaults.update(overrides)
    return Project(**defaults)


def test_get_todos_requires_bearer_token(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/todos", token=None)
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_get_todos_delegates_to_authz_and_returns_list(bridge):
    bridge["things"].todos = [_todo(id="t1", name="A"), _todo(id="t2", name="B")]
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 200
    assert bridge["authz"].last_token == "aa_test_token"
    assert bridge["authz"].last_scope == "things:read"
    assert bridge["authz"].last_description == "List Things todos"
    assert [t["id"] for t in data["todos"]] == ["t1", "t2"]


def test_get_todos_forwards_filters(bridge):
    _get(f"{bridge['url']}/things-bridge/todos?list=TMTodayListSource&project=p1&area=a1&tag=Urgent&status=open")
    kwargs = bridge["things"].last_list_todos_kwargs
    assert kwargs == {
        "list_id": "TMTodayListSource",
        "project_id": "p1",
        "area_id": "a1",
        "tag": "Urgent",
        "status": "open",
    }


def test_get_todos_token_expired_maps_to_401(bridge):
    bridge["authz"].raise_on_validate = AuthzTokenExpiredError("token_expired")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 401
    assert data == {"error": "token_expired"}


def test_get_todos_invalid_token_maps_to_401_unauthorized(bridge):
    bridge["authz"].raise_on_validate = AuthzTokenInvalidError("invalid_token")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_get_todos_scope_denied_maps_to_403(bridge):
    bridge["authz"].raise_on_validate = AuthzScopeDeniedError("scope_denied")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 403
    assert data == {"error": "scope_denied"}


def test_get_todos_authz_unavailable_maps_to_502(bridge):
    bridge["authz"].raise_on_validate = AuthzUnavailableError("unreachable")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 502
    assert data["error"] == "authz_unavailable"


def test_get_todos_things_error_maps_to_502(bridge):
    bridge["things"].raise_on_call = ThingsError("osascript blew up")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 502
    assert data["error"] == "things_unavailable"


def test_get_todos_things_permission_error_maps_to_503(bridge):
    bridge["things"].raise_on_call = ThingsPermissionError("grant automation")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 503
    assert data["error"] == "things_permission_denied"


def test_get_todo_by_id_returns_single(bridge):
    bridge["things"].todos_by_id = {"t1": _todo(id="t1", name="X")}
    status, data = _get(f"{bridge['url']}/things-bridge/todos/t1")
    assert status == 200
    assert data["todo"]["id"] == "t1"
    assert bridge["authz"].last_description == "Read Things todo t1"


def test_get_todo_not_found_returns_404(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/todos/nope")
    assert status == 404
    assert data["error"] == "not_found"


def test_get_projects_list(bridge):
    bridge["things"].projects = [_project(id="p1"), _project(id="p2")]
    status, data = _get(f"{bridge['url']}/things-bridge/projects")
    assert status == 200
    assert [p["id"] for p in data["projects"]] == ["p1", "p2"]


def test_get_project_by_id(bridge):
    bridge["things"].projects_by_id = {"p1": _project(id="p1")}
    status, data = _get(f"{bridge['url']}/things-bridge/projects/p1")
    assert status == 200
    assert data["project"]["id"] == "p1"


def test_get_areas_list(bridge):
    bridge["things"].areas = [Area(id="a1", name="Personal", tag_names=[])]
    status, data = _get(f"{bridge['url']}/things-bridge/areas")
    assert status == 200
    assert data["areas"][0]["id"] == "a1"


def test_get_area_by_id(bridge):
    bridge["things"].areas_by_id = {"a1": Area(id="a1", name="Personal", tag_names=["home"])}
    status, data = _get(f"{bridge['url']}/things-bridge/areas/a1")
    assert status == 200
    assert data["area"]["tag_names"] == ["home"]


def test_unknown_path_returns_404(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/nope")
    assert status == 404


def test_todo_id_over_length_returns_404(bridge):
    # Overly long ids are rejected before authz or AppleScript are involved,
    # so a caller cannot DoS or spam the JIT approval prompt with giant strings.
    long_id = "a" * 300
    status, data = _get(f"{bridge['url']}/things-bridge/todos/{long_id}")
    assert status == 404
    assert data == {"error": "not_found"}
    assert bridge["authz"].last_token is None


def test_safe_id_rejects_control_and_path_chars():
    # Unit test of the defence-in-depth guard that runs before authz/AppleScript.
    from things_bridge.server import _safe_id

    assert _safe_id("valid-id_123") == "valid-id_123"
    assert _safe_id(None) is None
    assert _safe_id("") is None
    assert _safe_id("a" * 300) is None
    assert _safe_id("foo/bar") is None
    assert _safe_id("foo\nbar") is None
    assert _safe_id("foo\tbar") is None
    assert _safe_id("foo\x00bar") is None
    assert _safe_id("foo\x7fbar") is None


def test_post_to_readonly_endpoint_returns_405(bridge):
    req = urllib.request.Request(
        f"{bridge['url']}/things-bridge/todos",
        data=b"{}",
        headers={"Authorization": "Bearer aa_test", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as exc:
        assert exc.code == 405
        assert exc.headers.get("Allow") == "GET"
        body = json.loads(exc.read())
        assert body == {"error": "method_not_allowed"}


def test_things_error_detail_not_leaked_in_response(bridge):
    # AppleScript stderr can contain filesystem paths and user names; the
    # bridge must not forward it to the HTTP client.
    bridge["things"].raise_on_call = ThingsError("/Users/secret/path leaked in stderr")
    status, data = _get(f"{bridge['url']}/things-bridge/todos")
    assert status == 502
    assert data == {"error": "things_unavailable"}
    assert "secret" not in json.dumps(data)
