# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the things-bridge HTTP server."""

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests.factories import make_project as _project
from tests.factories import make_todo as _todo
from tests.things_client_fake.store import FakeThingsClient, FakeThingsStore
from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config
from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
    ThingsError,
    ThingsPermissionError,
)
from things_bridge.server import ThingsBridgeServer
from things_models.models import Area


class FakeAuthz(AgentAuthClient):
    # Skip AgentAuthClient.__init__: tests never exercise the HTTP path.
    def __init__(self, *, raise_on_validate: Exception | None = None):
        self.raise_on_validate = raise_on_validate
        self.last_token: str | None = None
        self.last_scope: str | None = None
        self.last_description: str | None = None

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        self.last_token = token
        self.last_scope = required_scope
        self.last_description = description
        if self.raise_on_validate is not None:
            raise self.raise_on_validate


class _InjectableThings:
    """Wrap :class:`FakeThingsClient` with error-injection and call spying.

    Used by HTTP integration tests that need to assert the bridge maps
    ``ThingsError`` / ``ThingsPermissionError`` / arbitrary client failures
    to the right HTTP status, and to verify filter forwarding.
    """

    def __init__(self, store: FakeThingsStore):
        self.store = store
        self._client = FakeThingsClient(store)
        self.raise_on_call: Exception | None = None
        self.last_list_todos_kwargs: dict[str, Any] | None = None

    def list_todos(self, **kwargs):
        self.last_list_todos_kwargs = kwargs
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.list_todos(**kwargs)

    def get_todo(self, todo_id):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.get_todo(todo_id)

    def list_projects(self, *, area_id=None):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.list_projects(area_id=area_id)

    def get_project(self, project_id):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.get_project(project_id)

    def list_areas(self):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.list_areas()

    def get_area(self, area_id):
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self._client.get_area(area_id)


@pytest.fixture
def bridge():
    config = Config(host="127.0.0.1", port=0)
    authz = FakeAuthz()
    store = FakeThingsStore()
    things = _InjectableThings(store)
    server = ThingsBridgeServer(config, things, authz)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "url": f"http://127.0.0.1:{port}",
            "authz": authz,
            "store": store,
            "things": things,
            "server": server,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str, token: str | None = "aa_test_token") -> tuple[int, Any]:
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


def test_get_todos_requires_bearer_token(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos", token=None)
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_get_todos_delegates_to_authz_and_returns_list(bridge):
    bridge["store"].todos = [_todo(id="t1", name="A"), _todo(id="t2", name="B")]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 200
    assert bridge["authz"].last_token == "aa_test_token"
    assert bridge["authz"].last_scope == "things:read"
    assert bridge["authz"].last_description == "List Things todos"
    assert [t["id"] for t in data["todos"]] == ["t1", "t2"]


def test_get_todos_forwards_filters(bridge):
    _get(
        f"{bridge['url']}/things-bridge/v1/todos?list=TMTodayListSource&project=p1&area=a1&tag=Urgent&status=open"
    )
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
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 401
    assert data == {"error": "token_expired"}


def test_get_todos_invalid_token_maps_to_401_unauthorized(bridge):
    bridge["authz"].raise_on_validate = AuthzTokenInvalidError("invalid_token")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_get_todos_scope_denied_maps_to_403(bridge):
    bridge["authz"].raise_on_validate = AuthzScopeDeniedError("scope_denied")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 403
    assert data == {"error": "scope_denied"}


def test_get_todos_authz_unavailable_maps_to_502(bridge):
    bridge["authz"].raise_on_validate = AuthzUnavailableError("unreachable")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 502
    assert data["error"] == "authz_unavailable"


def test_get_todos_things_error_maps_to_502(bridge):
    bridge["things"].raise_on_call = ThingsError("osascript blew up")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 502
    assert data["error"] == "things_unavailable"


def test_get_todos_things_permission_error_maps_to_503(bridge):
    bridge["things"].raise_on_call = ThingsPermissionError("grant automation")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 503
    assert data["error"] == "things_permission_denied"


def test_get_todo_by_id_returns_single(bridge):
    bridge["store"].todos = [_todo(id="t1", name="X")]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos/t1")
    assert status == 200
    assert data["todo"]["id"] == "t1"
    assert bridge["authz"].last_description == "Read Things todo t1"


def test_get_todo_not_found_returns_404(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos/nope")
    assert status == 404
    assert data["error"] == "not_found"


def test_get_projects_list(bridge):
    bridge["store"].projects = [_project(id="p1"), _project(id="p2")]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/projects")
    assert status == 200
    assert [p["id"] for p in data["projects"]] == ["p1", "p2"]


def test_get_project_by_id(bridge):
    bridge["store"].projects = [_project(id="p1")]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/projects/p1")
    assert status == 200
    assert data["project"]["id"] == "p1"


def test_get_areas_list(bridge):
    bridge["store"].areas = [Area(id="a1", name="Personal", tag_names=[])]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/areas")
    assert status == 200
    assert data["areas"][0]["id"] == "a1"


def test_get_area_by_id(bridge):
    bridge["store"].areas = [Area(id="a1", name="Personal", tag_names=["home"])]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/areas/a1")
    assert status == 200
    assert data["area"]["tag_names"] == ["home"]


def test_unknown_path_returns_404(bridge):
    status, _data = _get(f"{bridge['url']}/things-bridge/nope")
    assert status == 404


def test_todo_id_over_length_returns_404(bridge):
    # Overly long ids are rejected before authz or AppleScript are involved,
    # so a caller cannot DoS or spam the JIT approval prompt with giant strings.
    long_id = "a" * 300
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos/{long_id}")
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
        f"{bridge['url']}/things-bridge/v1/todos",
        data=b"{}",
        headers={"Authorization": "Bearer aa_test", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected HTTPError")
    except urllib.error.HTTPError as exc:
        assert exc.code == 405
        assert exc.headers.get("Allow") == "GET"
        body = json.loads(exc.read())
        assert body == {"error": "method_not_allowed"}


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"])
def test_non_get_methods_return_405(bridge, method):
    # All non-GET methods should return a consistent 405 so probes cannot
    # distinguish whether a method is merely unimplemented (501) from
    # the stdlib default vs. explicitly disallowed on a read-only bridge.
    req = urllib.request.Request(
        f"{bridge['url']}/things-bridge/v1/todos",
        headers={"Authorization": "Bearer aa_test"},
        method=method,
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected HTTPError")
    except urllib.error.HTTPError as exc:
        assert exc.code == 405
        assert exc.headers.get("Allow") == "GET"


def test_things_error_detail_not_leaked_in_response(bridge):
    # AppleScript stderr can contain filesystem paths and user names; the
    # bridge must not forward it to the HTTP client.
    bridge["things"].raise_on_call = ThingsError("/Users/secret/path leaked in stderr")
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos")
    assert status == 502
    assert data == {"error": "things_unavailable"}
    assert "secret" not in json.dumps(data)
