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
from things_client_fake.store import FakeThingsClient, FakeThingsStore

from agent_auth_client import (
    AgentAuthClient,
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)
from tests_support.factories import make_project as _project
from tests_support.factories import make_todo as _todo
from things_bridge.config import Config
from things_bridge.errors import (
    ThingsError,
    ThingsPermissionError,
)
from things_bridge.metrics import build_registry as build_bridge_registry
from things_bridge.server import ThingsBridgeServer, _HealthChecker
from things_bridge.types import ThingsClientCommand, make_things_client_command
from things_models.models import Area, AreaId


class FakeAuthz(AgentAuthClient):
    # Initialise AgentAuthClient with a fake URL so any inherited method
    # (or future base-class attribute read) stays safe. validate() is
    # overridden below and never touches the URL.
    def __init__(self, *, raise_on_validate: Exception | None = None):
        super().__init__("http://test-fake")
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
    registry, metrics = build_bridge_registry()
    server = ThingsBridgeServer(config, things, authz, registry, metrics)
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


def _get_text(url: str, token: str | None = "aa_test_token"):
    """GET a text/plain endpoint, returning (status, content_type, body)."""
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (
                resp.status,
                resp.headers.get("Content-Type", ""),
                resp.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("Content-Type", "") if exc.headers else "",
            exc.read().decode("utf-8", errors="replace"),
        )


def test_get_todos_requires_bearer_token(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/v1/todos", token=None)
    assert status == 401
    assert data == {"error": "unauthorized"}


# -- /health depth -----------------------------------------------------------

# The /health handler must verify that ``things_client_command[0]`` is
# still resolvable before returning 200 — a bridge that can't reach its
# Things client binary isn't actually healthy. These tests pin both the
# success path and the 503 unhealthy path.


class _ResolverStub:
    """Callable stand-in for ``shutil.which`` with scripted responses."""

    def __init__(self, resolves: bool):
        self.resolves = resolves
        self.calls: list[str] = []

    def __call__(self, name: str) -> str | None:
        self.calls.append(name)
        return f"/fake/path/{name}" if self.resolves else None


def _bridge_with_health_checker(health_checker: _HealthChecker) -> dict[str, Any]:
    """Start a bridge under test with an injected :class:`_HealthChecker`.

    Mirrors the default ``bridge`` fixture but lets the caller wire a
    resolver stub in so /health 503 can be exercised without touching
    the real PATH.
    """
    config = Config(host="127.0.0.1", port=0)
    authz = FakeAuthz()
    store = FakeThingsStore()
    things = _InjectableThings(store)
    registry, metrics = build_bridge_registry()
    server = ThingsBridgeServer(
        config, things, authz, registry, metrics, health_checker=health_checker
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return {
        "url": f"http://127.0.0.1:{port}",
        "authz": authz,
        "server": server,
        "thread": thread,
    }


def _stop_bridge(handle: dict[str, Any]) -> None:
    handle["server"].shutdown()
    handle["server"].server_close()
    handle["thread"].join(timeout=2)


@pytest.mark.covers_function("Serve Bridge Health Endpoint")
def test_health_returns_503_when_things_client_unresolvable():
    resolver = _ResolverStub(resolves=False)
    checker = _HealthChecker(
        make_things_client_command(["things-client-cli-applescript"]), resolver=resolver
    )
    handle = _bridge_with_health_checker(checker)
    try:
        status, data = _get(f"{handle['url']}/things-bridge/health")
        assert status == 503
        assert data == {"status": "unhealthy"}
        assert resolver.calls == ["things-client-cli-applescript"]
    finally:
        _stop_bridge(handle)


@pytest.mark.covers_function("Serve Bridge Health Endpoint")
def test_health_returns_200_when_things_client_resolvable():
    resolver = _ResolverStub(resolves=True)
    checker = _HealthChecker(
        make_things_client_command(["things-client-cli-applescript"]), resolver=resolver
    )
    handle = _bridge_with_health_checker(checker)
    try:
        status, data = _get(f"{handle['url']}/things-bridge/health")
        assert status == 200
        assert data == {"status": "ok"}
    finally:
        _stop_bridge(handle)


@pytest.mark.covers_function("Serve Bridge Health Endpoint")
def test_health_checker_caches_resolution_within_ttl():
    # Cache TTL guarantees at most one PATH walk per window even under
    # a readiness-probe storm. Pin the clock and drive two calls inside
    # the TTL — the resolver must be queried exactly once.
    now = [100.0]
    resolver = _ResolverStub(resolves=True)
    checker = _HealthChecker(
        make_things_client_command(["things-client-cli-applescript"]),
        cache_ttl_seconds=30.0,
        clock=lambda: now[0],
        resolver=resolver,
    )
    assert checker.things_client_resolvable() is True
    now[0] += 29.0
    assert checker.things_client_resolvable() is True
    assert resolver.calls == ["things-client-cli-applescript"]


@pytest.mark.covers_function("Serve Bridge Health Endpoint")
def test_health_checker_requeries_after_ttl_expires():
    # After the TTL lapses, the next call must re-run the resolver —
    # otherwise a freshly-installed client could never flip health
    # back to green without a restart.
    now = [100.0]
    resolver = _ResolverStub(resolves=True)
    checker = _HealthChecker(
        make_things_client_command(["things-client-cli-applescript"]),
        cache_ttl_seconds=30.0,
        clock=lambda: now[0],
        resolver=resolver,
    )
    assert checker.things_client_resolvable() is True
    now[0] += 31.0
    assert checker.things_client_resolvable() is True
    assert len(resolver.calls) == 2


@pytest.mark.covers_function("Serve Bridge Health Endpoint")
def test_health_checker_rejects_empty_command():
    # Defensive: an empty ``things_client_command`` is a config bug.
    # Fail loud at construction rather than silently reporting healthy.
    # The NewType permits an empty tuple cast; _HealthChecker still
    # rejects it at runtime as a belt-and-braces guard.
    with pytest.raises(ValueError):
        _HealthChecker(ThingsClientCommand(()))


# -- /metrics ---------------------------------------------------------------

_EXPECTED_BRIDGE_METRIC_NAMES = (
    "http_server_request_duration_seconds",
    "http_server_active_requests",
)


def test_metrics_requires_bearer_token(bridge):
    status, data = _get(f"{bridge['url']}/things-bridge/metrics", token=None)
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_metrics_rejects_tokens_without_metrics_scope(bridge):
    bridge["authz"].raise_on_validate = AuthzScopeDeniedError("scope_denied")
    status, data = _get(f"{bridge['url']}/things-bridge/metrics")
    assert status == 403
    assert data == {"error": "scope_denied"}


def test_metrics_returns_prometheus_text_with_declared_metrics(bridge):
    status, content_type, body = _get_text(f"{bridge['url']}/things-bridge/metrics")
    assert status == 200
    assert content_type.startswith("text/plain")
    # The scrape calls authz.validate under the ``things-bridge:metrics``
    # scope. Our FakeAuthz accepts anything that doesn't raise.
    assert bridge["authz"].last_scope == "things-bridge:metrics"
    # Contract: every declared metric name appears in the exposition.
    # Names are inlined (not looped via a module constant) so
    # scripts/verify-standards.sh can regex-match this block — a
    # rename breaks both places at once.
    assert "# TYPE http_server_request_duration_seconds" in body
    assert "# TYPE http_server_active_requests" in body


def test_metrics_authz_unavailable_maps_to_502(bridge):
    bridge["authz"].raise_on_validate = AuthzUnavailableError("unreachable")
    status, data = _get(f"{bridge['url']}/things-bridge/metrics")
    assert status == 502
    assert data["error"] == "authz_unavailable"


def test_metrics_scrape_records_its_own_http_duration(bridge):
    _get_text(f"{bridge['url']}/things-bridge/metrics")
    status, _ct, body = _get_text(f"{bridge['url']}/things-bridge/metrics")
    assert status == 200
    assert 'route="/things-bridge/metrics"' in body
    assert "http_server_request_duration_seconds_bucket" in body


def test_metrics_id_carrying_route_uses_templated_label(bridge):
    # Probe a todo-by-id path — the metric label should collapse the
    # ``{id}`` segment so cardinality stays bounded.
    _get(f"{bridge['url']}/things-bridge/v1/todos/t1")
    status, _ct, body = _get_text(f"{bridge['url']}/things-bridge/metrics")
    assert status == 200
    assert 'route="/things-bridge/v1/todos/{id}"' in body
    assert 'route="/things-bridge/v1/todos/t1"' not in body


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


def test_get_todos_authz_rate_limited_forwards_429_and_retry_after(bridge):
    # Pin the contract: agent-auth is the sole rate-limit authority,
    # and the bridge passes both the 429 and the upstream Retry-After
    # through verbatim so clients can pace themselves without
    # re-negotiating against the bridge's own (non-existent) bucket.
    bridge["authz"].raise_on_validate = AuthzRateLimitedError("rate_limited", retry_after_seconds=9)
    req = urllib.request.Request(
        f"{bridge['url']}/things-bridge/v1/todos",
        headers={"Authorization": "Bearer aa_test_token"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 429
        assert json.loads(exc.read()) == {"error": "rate_limited"}
        assert exc.headers.get("Retry-After") == "9"
    else:
        raise AssertionError("bridge did not return 429")


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
    bridge["store"].areas = [Area(id=AreaId("a1"), name="Personal", tag_names=[])]
    status, data = _get(f"{bridge['url']}/things-bridge/v1/areas")
    assert status == 200
    assert data["areas"][0]["id"] == "a1"


def test_get_area_by_id(bridge):
    bridge["store"].areas = [Area(id=AreaId("a1"), name="Personal", tag_names=["home"])]
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
