# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the error-code taxonomy.

Every error code documented in ``design/error-codes.md`` is exercised here.
Each test triggers the precise condition that should produce a given code and
asserts the response body. Changes to error strings or HTTP statuses will
fail these tests, which is the intent: the error taxonomy is public API.

Documented codes
----------------
agent-auth /v1/validate:
  malformed_request (400), invalid_token (401), token_expired (401),
  token_revoked (401), scope_denied (403).
agent-auth /v1/token/refresh:
  malformed_request (400), invalid_token (401), family_revoked (401),
  refresh_token_expired (401), refresh_token_reuse_detected (401).
agent-auth /v1/token/reissue:
  malformed_request (400), refresh_token_still_valid (400),
  family_revoked (401), reissue_denied (403).
agent-auth /health (unversioned):
  missing_token (401), invalid_token (401), token_expired (401),
  scope_denied (403).
agent-auth /metrics (unversioned):
  missing_token (401), invalid_token (401), token_expired (401),
  scope_denied (403).
agent-auth server-wide:
  not_found (404).
things-bridge /v1/* data endpoints:
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502), not_found (404),
  things_permission_denied (503), things_unavailable (502).
things-bridge /health (unversioned):
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502).
things-bridge /metrics (unversioned):
  unauthorized (401), token_expired (401), scope_denied (403),
  authz_unavailable (502).
things-bridge server-wide:
  not_found (404), method_not_allowed (405).
"""

import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.metrics import build_registry as build_auth_registry
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests._http import get, post
from tests.things_client_fake.store import FakeThingsClient, FakeThingsStore
from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config as BridgeConfig
from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzUnavailableError,
    ThingsError,
    ThingsPermissionError,
)
from things_bridge.metrics import build_registry as build_bridge_registry
from things_bridge.server import ThingsBridgeServer

# -- test infrastructure --


class _DenyPlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=False)


@pytest.fixture
def auth_server(tmp_dir, signing_key, encryption_key):
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(_DenyPlugin(), store, audit)
    registry, metrics = build_auth_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield config, signing_key, store, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _expire_token(db_path: str, token_id: str) -> None:
    """Directly back-date a token's expiry to the past so the server treats it as expired."""
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE tokens SET expires_at = ? WHERE id = ?", (past, token_id))


def _extract_token_id(raw_token: str) -> str:
    """Extract the token_id segment from a raw token string."""
    return raw_token.split("_")[1]


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


# == agent-auth: POST /agent-auth/v1/validate ==


def test_validate_malformed_request(auth_server):
    _, _, _, base = auth_server
    status, body = post(f"{base}/agent-auth/v1/validate", raw=b"{not json")
    assert status == 400
    assert body["error"] == "malformed_request"


def test_validate_invalid_token(auth_server):
    _, _, _, base = auth_server
    status, body = post(
        f"{base}/agent-auth/v1/validate",
        {"token": "aa_fake_badsig", "required_scope": "things:read"},
    )
    assert status == 401
    assert body["error"] == "invalid_token"
    assert body["valid"] is False


def test_validate_token_expired(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-exp"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    token_id = _extract_token_id(access_token)
    _expire_token(config.db_path, token_id)
    status, body = post(
        f"{base}/agent-auth/v1/validate",
        {"token": access_token, "required_scope": "things:read"},
    )
    assert status == 401
    assert body["error"] == "token_expired"
    assert body["valid"] is False


def test_validate_token_revoked(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-rev"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    store.mark_family_revoked(family_id)
    status, body = post(
        f"{base}/agent-auth/v1/validate",
        {"token": access_token, "required_scope": "things:read"},
    )
    assert status == 401
    assert body["error"] == "token_revoked"
    assert body["valid"] is False


def test_validate_scope_denied(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-scope"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    status, body = post(
        f"{base}/agent-auth/v1/validate",
        {"token": access_token, "required_scope": "agent-auth:admin"},
    )
    assert status == 403
    assert body["error"] == "scope_denied"
    assert body["valid"] is False


# == agent-auth: POST /agent-auth/v1/token/refresh ==


def test_refresh_malformed_request(auth_server):
    _, _, _, base = auth_server
    status, body = post(f"{base}/agent-auth/v1/token/refresh", raw=b"{not json")
    assert status == 400
    assert body["error"] == "malformed_request"


def test_refresh_invalid_token(auth_server):
    _, _, _, base = auth_server
    status, body = post(f"{base}/agent-auth/v1/token/refresh", {"refresh_token": "rt_fake_badsig"})
    assert status == 401
    assert body["error"] == "invalid_token"


def test_refresh_family_revoked(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-ref-rev"
    store.create_family(family_id, {"things:read": "allow"})
    _, refresh_token = create_token_pair(signing_key, store, family_id, config)
    store.mark_family_revoked(family_id)
    status, body = post(f"{base}/agent-auth/v1/token/refresh", {"refresh_token": refresh_token})
    assert status == 401
    assert body["error"] == "family_revoked"


def test_refresh_token_expired(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-ref-exp"
    store.create_family(family_id, {"things:read": "allow"})
    _, refresh_token = create_token_pair(signing_key, store, family_id, config)
    token_id = _extract_token_id(refresh_token)
    _expire_token(config.db_path, token_id)
    status, body = post(f"{base}/agent-auth/v1/token/refresh", {"refresh_token": refresh_token})
    assert status == 401
    assert body["error"] == "refresh_token_expired"


def test_refresh_token_reuse_detected(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-reuse"
    store.create_family(family_id, {"things:read": "allow"})
    _, refresh_token = create_token_pair(signing_key, store, family_id, config)
    post(f"{base}/agent-auth/v1/token/refresh", {"refresh_token": refresh_token})
    status, body = post(f"{base}/agent-auth/v1/token/refresh", {"refresh_token": refresh_token})
    assert status == 401
    assert body["error"] == "refresh_token_reuse_detected"


# == agent-auth: POST /agent-auth/v1/token/reissue ==


def test_reissue_malformed_request(auth_server):
    _, _, _, base = auth_server
    status, body = post(f"{base}/agent-auth/v1/token/reissue", raw=b"{not json")
    assert status == 400
    assert body["error"] == "malformed_request"


def test_reissue_refresh_token_still_valid(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-reissue-valid"
    store.create_family(family_id, {"things:read": "allow"})
    create_token_pair(signing_key, store, family_id, config)
    status, body = post(f"{base}/agent-auth/v1/token/reissue", {"family_id": family_id})
    assert status == 400
    assert body["error"] == "refresh_token_still_valid"


def test_reissue_family_revoked(auth_server):
    _, _, store, base = auth_server
    family_id = "fam-reissue-rev"
    store.create_family(family_id, {"things:read": "allow"})
    store.mark_family_revoked(family_id)
    status, body = post(f"{base}/agent-auth/v1/token/reissue", {"family_id": family_id})
    assert status == 401
    assert body["error"] == "family_revoked"


def test_reissue_denied(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-reissue-deny"
    store.create_family(family_id, {"things:read": "allow"})
    _, refresh_token = create_token_pair(signing_key, store, family_id, config)
    token_id = _extract_token_id(refresh_token)
    _expire_token(config.db_path, token_id)
    status, body = post(f"{base}/agent-auth/v1/token/reissue", {"family_id": family_id})
    assert status == 403
    assert body["error"] == "reissue_denied"


# == agent-auth: GET /agent-auth/health (unversioned) ==


def test_health_missing_token(auth_server):
    _, _, _, base = auth_server
    status, body = get(f"{base}/agent-auth/health")
    assert status == 401
    assert body["error"] == "missing_token"


def test_health_invalid_token(auth_server):
    _, _, _, base = auth_server
    status, body = get(f"{base}/agent-auth/health", _bearer("aa_fake_badsig"))
    assert status == 401
    assert body["error"] == "invalid_token"


def test_health_token_expired(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-health-exp"
    store.create_family(family_id, {"agent-auth:health": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    token_id = _extract_token_id(access_token)
    _expire_token(config.db_path, token_id)
    status, body = get(f"{base}/agent-auth/health", _bearer(access_token))
    assert status == 401
    assert body["error"] == "token_expired"


def test_health_scope_denied(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-health-scope"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    status, body = get(f"{base}/agent-auth/health", _bearer(access_token))
    assert status == 403
    assert body["error"] == "scope_denied"


# == agent-auth: GET /agent-auth/metrics (unversioned) ==


def test_metrics_missing_token(auth_server):
    _, _, _, base = auth_server
    status, body = get(f"{base}/agent-auth/metrics")
    assert status == 401
    assert body["error"] == "missing_token"


def test_metrics_invalid_token(auth_server):
    _, _, _, base = auth_server
    status, body = get(f"{base}/agent-auth/metrics", _bearer("aa_fake_badsig"))
    assert status == 401
    assert body["error"] == "invalid_token"


def test_metrics_token_expired(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-metrics-exp"
    store.create_family(family_id, {"agent-auth:metrics": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    token_id = _extract_token_id(access_token)
    _expire_token(config.db_path, token_id)
    status, body = get(f"{base}/agent-auth/metrics", _bearer(access_token))
    assert status == 401
    assert body["error"] == "token_expired"


def test_metrics_scope_denied(auth_server):
    config, signing_key, store, base = auth_server
    family_id = "fam-metrics-scope"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)
    status, body = get(f"{base}/agent-auth/metrics", _bearer(access_token))
    assert status == 403
    assert body["error"] == "scope_denied"


# == agent-auth: server-wide ==


def test_agent_auth_not_found(auth_server):
    _, _, _, base = auth_server
    status, body = get(f"{base}/agent-auth/v1/does-not-exist")
    assert status == 404
    assert body["error"] == "not_found"


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
