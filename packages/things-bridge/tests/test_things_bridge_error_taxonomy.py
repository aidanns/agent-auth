# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the things-bridge half of the error-code taxonomy.

The error taxonomy is split across two packages — things-bridge's
response codes are exercised here, and agent-auth's response codes are
exercised in
``packages/agent-auth/tests/test_error_taxonomy.py``. The split keeps
each package's unit-test shard self-contained: the bridge tests need
``things_client_fake``, which lives under ``packages/things-bridge/tests/``
as a test-only fake and is only on the things-bridge shard's pythonpath.

Every error code documented in ``design/error-codes.md`` is exercised by
exactly one of the two files. Each test triggers the precise condition
that should produce a given code and asserts the response body. Changes
to error strings or HTTP statuses will fail these tests, which is the
intent: the error taxonomy is public API.

Documented codes covered here
-----------------------------
things-bridge /v1/* data endpoints:
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502), not_found (404),
  things_permission_denied (503), things_unavailable (502),
  rate_limited (429).
things-bridge /health (unversioned):
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502).
things-bridge /metrics (unversioned):
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502).
things-bridge server-wide:
  not_found (404), method_not_allowed (405).
"""

import threading

import pytest
from things_client_fake.store import FakeThingsClient, FakeThingsStore

from agent_auth_client import (
    AgentAuthClient,
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzUnavailableError,
)
from tests_support.http import get, post
from things_bridge.config import Config as BridgeConfig
from things_bridge.errors import (
    ThingsError,
    ThingsPermissionError,
)
from things_bridge.metrics import build_registry as build_bridge_registry
from things_bridge.server import ThingsBridgeServer

# -- test infrastructure --


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeAuthz(AgentAuthClient):
    def __init__(self) -> None:
        super().__init__("http://test-fake")
        self.exc: Exception | None = None

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        if self.exc is not None:
            raise self.exc


class _InjectableThings:
    """Wraps FakeThingsClient with error-injection for taxonomy tests."""

    exc: Exception | None = None

    def __init__(self, store: FakeThingsStore):
        self._client = FakeThingsClient(store)

    def list_todos(self, **kwargs):
        if self.exc is not None:
            raise self.exc
        return self._client.list_todos(**kwargs)

    def get_todo(self, todo_id):
        if self.exc is not None:
            raise self.exc
        return self._client.get_todo(todo_id)

    def list_projects(self, **kwargs):
        if self.exc is not None:
            raise self.exc
        return self._client.list_projects(**kwargs)

    def get_project(self, project_id):
        if self.exc is not None:
            raise self.exc
        return self._client.get_project(project_id)

    def list_areas(self):
        if self.exc is not None:
            raise self.exc
        return self._client.list_areas()

    def get_area(self, area_id):
        if self.exc is not None:
            raise self.exc
        return self._client.get_area(area_id)


@pytest.fixture
def bridge_server():
    config = BridgeConfig(host="127.0.0.1", port=0)
    authz = _FakeAuthz()
    store = FakeThingsStore()
    things = _InjectableThings(store)
    registry, metrics = build_bridge_registry()
    server = ThingsBridgeServer(config, things, authz, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield authz, things, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# == things-bridge: GET /things-bridge/v1/todos (authorization errors) ==


def test_bridge_unauthorized_no_token(bridge_server):
    _, _, base = bridge_server
    status, body = get(f"{base}/things-bridge/v1/todos")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_bridge_token_expired(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzTokenExpiredError("expired")
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 401
    assert body["error"] == "token_expired"


def test_bridge_scope_denied(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzScopeDeniedError("denied")
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 403
    assert body["error"] == "scope_denied"


def test_bridge_authz_unavailable(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzUnavailableError("down")
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 502
    assert body["error"] == "authz_unavailable"


def test_bridge_not_found_unknown_id(bridge_server):
    _, _, base = bridge_server
    status, body = get(f"{base}/things-bridge/v1/todos/nonexistent-id", _bearer("tok"))
    assert status == 404
    assert body["error"] == "not_found"


def test_bridge_things_permission_denied(bridge_server):
    _, things, base = bridge_server
    things.exc = ThingsPermissionError("denied")
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 503
    assert body["error"] == "things_permission_denied"


def test_bridge_rate_limited(bridge_server):
    # Coverage for the 429 passthrough path — agent-auth returns 429,
    # the bridge maps AuthzRateLimitedError back to 429 with the same
    # Retry-After (see ADR 0027).
    authz, _, base = bridge_server
    authz.exc = AuthzRateLimitedError("rate_limited", retry_after_seconds=3)
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 429
    assert body["error"] == "rate_limited"


def test_bridge_things_unavailable(bridge_server):
    _, things, base = bridge_server
    things.exc = ThingsError("subprocess failed")
    status, body = get(f"{base}/things-bridge/v1/todos", _bearer("tok"))
    assert status == 502
    assert body["error"] == "things_unavailable"


# == things-bridge: GET /things-bridge/health (unversioned) ==


def test_bridge_health_unauthorized_no_token(bridge_server):
    _, _, base = bridge_server
    status, body = get(f"{base}/things-bridge/health")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_bridge_health_token_expired(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzTokenExpiredError("expired")
    status, body = get(f"{base}/things-bridge/health", _bearer("tok"))
    assert status == 401
    assert body["error"] == "token_expired"


def test_bridge_health_scope_denied(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzScopeDeniedError("denied")
    status, body = get(f"{base}/things-bridge/health", _bearer("tok"))
    assert status == 403
    assert body["error"] == "scope_denied"


def test_bridge_health_authz_unavailable(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzUnavailableError("down")
    status, body = get(f"{base}/things-bridge/health", _bearer("tok"))
    assert status == 502
    assert body["error"] == "authz_unavailable"


# == things-bridge: GET /things-bridge/metrics (unversioned) ==


def test_bridge_metrics_unauthorized_no_token(bridge_server):
    _, _, base = bridge_server
    status, body = get(f"{base}/things-bridge/metrics")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_bridge_metrics_token_expired(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzTokenExpiredError("expired")
    status, body = get(f"{base}/things-bridge/metrics", _bearer("tok"))
    assert status == 401
    assert body["error"] == "token_expired"


def test_bridge_metrics_scope_denied(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzScopeDeniedError("denied")
    status, body = get(f"{base}/things-bridge/metrics", _bearer("tok"))
    assert status == 403
    assert body["error"] == "scope_denied"


def test_bridge_metrics_authz_unavailable(bridge_server):
    authz, _, base = bridge_server
    authz.exc = AuthzUnavailableError("down")
    status, body = get(f"{base}/things-bridge/metrics", _bearer("tok"))
    assert status == 502
    assert body["error"] == "authz_unavailable"


# == things-bridge: server-wide ==


def test_bridge_not_found_unknown_path(bridge_server):
    _, _, base = bridge_server
    status, body = get(f"{base}/things-bridge/v1/does-not-exist", _bearer("tok"))
    assert status == 404
    assert body["error"] == "not_found"


def test_bridge_method_not_allowed(bridge_server):
    _, _, base = bridge_server
    status, body = post(f"{base}/things-bridge/v1/todos", {})
    assert status == 405
    assert body["error"] == "method_not_allowed"
