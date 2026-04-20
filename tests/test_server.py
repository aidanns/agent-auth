"""In-process handler-edge-case tests; HTTP lifecycle lives in tests/integration/."""

import os
import threading

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.server import AgentAuthHandler, AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests._http import get, post


def _issue_health_token(server, store, scopes):
    family_id = "fam-health-test"
    store.create_family(family_id, scopes)
    access_token, _ = create_token_pair(server.signing_key, store, family_id, server.config)
    return access_token


def _health_headers(token):
    return {"Authorization": f"Bearer {token}"}


class _DenyPlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=False)


@pytest.fixture
def in_process_server(tmp_dir, signing_key, encryption_key):
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(_DenyPlugin(), store, audit)
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{port}", store
    finally:
        server.shutdown()


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_returns_ok_when_store_reachable(in_process_server):
    server, base, store = in_process_server
    token = _issue_health_token(server, store, {"agent-auth:health": "allow"})
    status, body = get(f"{base}/agent-auth/health", _health_headers(token))
    assert status == 200
    assert body == {"status": "ok"}


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_returns_unhealthy_when_store_ping_fails(in_process_server, monkeypatch):
    server, base, store = in_process_server
    token = _issue_health_token(server, store, {"agent-auth:health": "allow"})

    def boom():
        raise RuntimeError("store offline")

    monkeypatch.setattr(store, "ping", boom)
    status, body = get(f"{base}/agent-auth/health", _health_headers(token))
    assert status == 503
    assert body == {"status": "unhealthy"}


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_requires_a_bearer_token(in_process_server):
    _, base, _ = in_process_server
    status, body = get(f"{base}/agent-auth/health")
    assert status == 401
    assert body["error"] == "missing_token"


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_rejects_tokens_without_the_health_scope(in_process_server):
    server, base, store = in_process_server
    token = _issue_health_token(server, store, {"things:read": "allow"})
    status, body = get(f"{base}/agent-auth/health", _health_headers(token))
    assert status == 403
    assert body["error"] == "scope_denied"


def test_unknown_get_route_returns_404(in_process_server):
    _, base, _ = in_process_server
    status, body = get(f"{base}/agent-auth/does-not-exist")
    assert status == 404
    assert body["error"] == "not_found"


def test_unknown_post_route_returns_404(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/does-not-exist", data={})
    assert status == 404
    assert body["error"] == "not_found"


def test_malformed_json_returns_400(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/v1/validate", raw=b"{not json")
    assert status == 400
    assert body["error"] == "malformed_request"


def test_oversize_body_returns_400(in_process_server):
    _, base, _ = in_process_server
    payload = b'{"token":"' + b"x" * (AgentAuthHandler.MAX_BODY_SIZE + 1) + b'"}'
    status, body = post(f"{base}/agent-auth/v1/validate", raw=payload)
    assert status == 400
    assert body["error"] == "malformed_request"
