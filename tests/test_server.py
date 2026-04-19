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
    status, body = post(f"{base}/agent-auth/validate", raw=b"{not json")
    assert status == 400
    assert body["error"] == "malformed_request"


def test_oversize_body_returns_400(in_process_server):
    _, base, _ = in_process_server
    payload = b'{"token":"' + b"x" * (AgentAuthHandler.MAX_BODY_SIZE + 1) + b'"}'
    status, body = post(f"{base}/agent-auth/validate", raw=payload)
    assert status == 400
    assert body["error"] == "malformed_request"


# --- token create ---


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_returns_tokens_and_family(in_process_server):
    _, base, _ = in_process_server
    status, body = post(
        f"{base}/agent-auth/token/create",
        data={"scopes": {"things:read": "allow"}},
    )
    assert status == 200
    assert body["family_id"]
    assert body["access_token"].startswith("aa_")
    assert body["refresh_token"].startswith("rt_")
    assert body["scopes"] == {"things:read": "allow"}
    assert isinstance(body["expires_in"], int)


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_empty_scopes(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/create", data={"scopes": {}})
    assert status == 400
    assert body["error"] == "no_scopes"


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_missing_scopes_field(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/create", data={})
    assert status == 400
    assert body["error"] == "no_scopes"


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_malformed_json(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/create", raw=b"{bad")
    assert status == 400
    assert body["error"] == "malformed_request"


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_invalid_tier(in_process_server):
    _, base, _ = in_process_server
    status, body = post(
        f"{base}/agent-auth/token/create",
        data={"scopes": {"things:read": "banana"}},
    )
    assert status == 400
    assert body["error"] == "invalid_tier"


# --- token list ---


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_returns_empty_array_when_no_families(in_process_server):
    _, base, _ = in_process_server
    status, body = get(f"{base}/agent-auth/token/list")
    assert status == 200
    assert body == []


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_returns_created_family(in_process_server):
    _, base, store = in_process_server
    post(f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}})
    status, body = get(f"{base}/agent-auth/token/list")
    assert status == 200
    assert len(body) == 1
    assert body[0]["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_includes_revoked_families(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]
    post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})

    status, body = get(f"{base}/agent-auth/token/list")
    assert status == 200
    assert any(f["id"] == family_id and f["revoked"] for f in body)


# --- token modify ---


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_adds_scope(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]

    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": family_id, "add_scopes": {"things:write": "prompt"}},
    )
    assert status == 200
    assert body["scopes"] == {"things:read": "allow", "things:write": "prompt"}


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_removes_scope(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create",
        data={"scopes": {"things:read": "allow", "things:write": "prompt"}},
    )
    family_id = create_body["family_id"]

    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": family_id, "remove_scopes": ["things:write"]},
    )
    assert status == 200
    assert body["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_returns_404_for_unknown_family(in_process_server):
    _, base, _ = in_process_server
    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": "no-such-family", "add_scopes": {"x": "allow"}},
    )
    assert status == 404
    assert body["error"] == "family_not_found"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_returns_409_for_revoked_family(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]
    post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})

    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": family_id, "add_scopes": {"x": "allow"}},
    )
    assert status == 409
    assert body["error"] == "family_revoked"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_returns_400_when_no_modifications_provided(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": create_body["family_id"]},
    )
    assert status == 400
    assert body["error"] == "no_modifications"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_rejects_invalid_tier_in_add_scopes(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": create_body["family_id"], "add_scopes": {"things:write": "banana"}},
    )
    assert status == 400
    assert body["error"] == "invalid_tier"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_set_tiers_silently_skips_unknown_scope(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]

    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": family_id, "set_tiers": {"no-such-scope": "prompt"}},
    )
    assert status == 200
    assert body["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_rejects_malformed_json(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/modify", raw=b"{bad")
    assert status == 400
    assert body["error"] == "malformed_request"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_rejects_missing_family_id(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/modify", data={"add_scopes": {"x": "allow"}})
    assert status == 400
    assert body["error"] == "malformed_request"


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_rejects_wrong_type_for_add_scopes(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    status, body = post(
        f"{base}/agent-auth/token/modify",
        data={"family_id": create_body["family_id"], "add_scopes": "not-a-dict"},
    )
    assert status == 400
    assert body["error"] == "malformed_request"


# --- token revoke ---


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_marks_family_revoked(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]
    access_token = create_body["access_token"]

    status, body = post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})
    assert status == 200
    assert body == {"family_id": family_id, "revoked": True}

    validate_status, validate_body = post(
        f"{base}/agent-auth/validate",
        data={"token": access_token, "required_scope": "things:read"},
    )
    assert validate_status == 401
    assert validate_body["valid"] is False


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_is_idempotent_on_already_revoked_family(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]
    post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})

    status, body = post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})
    assert status == 200
    assert body["revoked"] is True


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_returns_404_for_unknown_family(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/revoke", data={"family_id": "no-such"})
    assert status == 404
    assert body["error"] == "family_not_found"


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_rejects_malformed_json(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/revoke", raw=b"{bad")
    assert status == 400
    assert body["error"] == "malformed_request"


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_rejects_missing_family_id(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/revoke", data={})
    assert status == 400
    assert body["error"] == "malformed_request"


# --- token rotate ---


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_revokes_old_and_creates_new_family(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    old_family_id = create_body["family_id"]
    old_access_token = create_body["access_token"]

    status, body = post(f"{base}/agent-auth/token/rotate", data={"family_id": old_family_id})
    assert status == 200
    assert body["old_family_id"] == old_family_id
    assert body["new_family_id"] != old_family_id
    assert body["access_token"].startswith("aa_")
    assert body["refresh_token"].startswith("rt_")
    assert body["scopes"] == {"things:read": "allow"}

    old_validate_status, old_validate_body = post(
        f"{base}/agent-auth/validate",
        data={"token": old_access_token, "required_scope": "things:read"},
    )
    assert old_validate_status == 401
    assert old_validate_body["valid"] is False

    new_validate_status, new_validate_body = post(
        f"{base}/agent-auth/validate",
        data={"token": body["access_token"], "required_scope": "things:read"},
    )
    assert new_validate_status == 200
    assert new_validate_body["valid"] is True


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_returns_404_for_unknown_family(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/rotate", data={"family_id": "no-such"})
    assert status == 404
    assert body["error"] == "family_not_found"


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_returns_409_for_revoked_family(in_process_server):
    _, base, _ = in_process_server
    _, create_body = post(
        f"{base}/agent-auth/token/create", data={"scopes": {"things:read": "allow"}}
    )
    family_id = create_body["family_id"]
    post(f"{base}/agent-auth/token/revoke", data={"family_id": family_id})

    status, body = post(f"{base}/agent-auth/token/rotate", data={"family_id": family_id})
    assert status == 409
    assert body["error"] == "family_revoked"


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_rejects_malformed_json(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/rotate", raw=b"{bad")
    assert status == 400
    assert body["error"] == "malformed_request"


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_rejects_missing_family_id(in_process_server):
    _, base, _ = in_process_server
    status, body = post(f"{base}/agent-auth/token/rotate", data={})
    assert status == 400
    assert body["error"] == "malformed_request"
