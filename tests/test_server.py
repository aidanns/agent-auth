"""Integration tests for the agent-auth HTTP server."""

import json
import os
import threading
import urllib.request
import urllib.error

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.keys import KeyManager
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import (
    PREFIX_ACCESS,
    PREFIX_REFRESH,
    generate_token_id,
    sign_token,
)


class AutoApprovePlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=True, grant_type="once")


class AutoDenyPlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=False)


@pytest.fixture
def server_env(tmp_dir, signing_key, encryption_key):
    config = Config(
        config_dir=tmp_dir,
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    return config, signing_key, store, audit


def _start_server(config, signing_key, store, audit, plugin=None):
    if plugin is None:
        plugin = AutoApprovePlugin()
    approval_manager = ApprovalManager(plugin, store, audit)
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def _create_test_tokens(signing_key, store, scopes=None):
    """Create a test token family and return (family_id, access_token, refresh_token)."""
    from datetime import datetime, timezone, timedelta

    scopes = scopes or {"things:read": "allow"}
    family_id = generate_token_id()
    store.create_family(family_id, scopes)

    now = datetime.now(timezone.utc)
    access_id = generate_token_id()
    access_token = sign_token(access_id, PREFIX_ACCESS, signing_key)
    _, _, access_sig = access_token.split("_")
    store.create_token(access_id, access_sig, family_id, "access",
                       (now + timedelta(hours=1)).isoformat())

    refresh_id = generate_token_id()
    refresh_token = sign_token(refresh_id, PREFIX_REFRESH, signing_key)
    _, _, refresh_sig = refresh_token.split("_")
    store.create_token(refresh_id, refresh_sig, family_id, "refresh",
                       (now + timedelta(hours=8)).isoformat())

    return family_id, access_token, refresh_token


def _post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# -- Validate endpoint tests --

def test_validate_allow(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        _, access_token, _ = _create_test_tokens(signing_key, store)
        status, body = _post(f"{base}/agent-auth/validate", {
            "token": access_token,
            "required_scope": "things:read",
        })
        assert status == 200
        assert body["valid"] is True
    finally:
        server.shutdown()


def test_validate_invalid_token(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        status, body = _post(f"{base}/agent-auth/validate", {
            "token": "aa_fake_bad",
            "required_scope": "things:read",
        })
        assert status == 401
        assert body["valid"] is False
    finally:
        server.shutdown()


def test_validate_scope_denied(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        _, access_token, _ = _create_test_tokens(signing_key, store)
        status, body = _post(f"{base}/agent-auth/validate", {
            "token": access_token,
            "required_scope": "things:write",
        })
        assert status == 403
        assert body["error"] == "scope_denied"
    finally:
        server.shutdown()


def test_validate_prompt_tier_approved(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit, AutoApprovePlugin())
    try:
        scopes = {"things:write": "prompt"}
        _, access_token, _ = _create_test_tokens(signing_key, store, scopes)
        status, body = _post(f"{base}/agent-auth/validate", {
            "token": access_token,
            "required_scope": "things:write",
            "description": "Complete todo: Buy milk",
        })
        assert status == 200
        assert body["valid"] is True
    finally:
        server.shutdown()


def test_validate_prompt_tier_denied(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit, AutoDenyPlugin())
    try:
        scopes = {"things:write": "prompt"}
        _, access_token, _ = _create_test_tokens(signing_key, store, scopes)
        status, body = _post(f"{base}/agent-auth/validate", {
            "token": access_token,
            "required_scope": "things:write",
        })
        assert status == 403
        assert body["error"] == "scope_denied"
    finally:
        server.shutdown()


# -- Refresh endpoint tests --

def test_refresh_success(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        _, _, refresh_token = _create_test_tokens(signing_key, store)
        status, body = _post(f"{base}/agent-auth/token/refresh", {
            "refresh_token": refresh_token,
        })
        assert status == 200
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["expires_in"] == 900
    finally:
        server.shutdown()


def test_refresh_reuse_detection(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        family_id, _, refresh_token = _create_test_tokens(signing_key, store)

        status1, body1 = _post(f"{base}/agent-auth/token/refresh", {
            "refresh_token": refresh_token,
        })
        assert status1 == 200

        status2, body2 = _post(f"{base}/agent-auth/token/refresh", {
            "refresh_token": refresh_token,
        })
        assert status2 == 401
        assert body2["error"] == "refresh_token_reuse_detected"

        family = store.get_family(family_id)
        assert family["revoked"] is True
    finally:
        server.shutdown()


# -- Status endpoint tests --

def test_status(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        _, access_token, _ = _create_test_tokens(signing_key, store)
        status, body = _get(f"{base}/agent-auth/token/status", {
            "Authorization": f"Bearer {access_token}",
        })
        assert status == 200
        assert body["type"] == "access"
        assert "scopes" in body
        assert "expires_in" in body
    finally:
        server.shutdown()


def test_status_missing_token(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        status, body = _get(f"{base}/agent-auth/token/status")
        assert status == 401
    finally:
        server.shutdown()


# -- Reissue endpoint tests --

def test_reissue_approved(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit, AutoApprovePlugin())
    try:
        family_id, _, _ = _create_test_tokens(signing_key, store)
        status, body = _post(f"{base}/agent-auth/token/reissue", {
            "family_id": family_id,
        })
        assert status == 200
        assert "access_token" in body
        assert "refresh_token" in body
    finally:
        server.shutdown()


def test_reissue_denied(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit, AutoDenyPlugin())
    try:
        family_id, _, _ = _create_test_tokens(signing_key, store)
        status, body = _post(f"{base}/agent-auth/token/reissue", {
            "family_id": family_id,
        })
        assert status == 403
        assert body["error"] == "reissue_denied"
    finally:
        server.shutdown()


def test_reissue_revoked_family(server_env, signing_key):
    config, signing_key, store, audit = server_env
    server, base = _start_server(config, signing_key, store, audit)
    try:
        family_id, _, _ = _create_test_tokens(signing_key, store)
        store.mark_family_revoked(family_id)
        status, body = _post(f"{base}/agent-auth/token/reissue", {
            "family_id": family_id,
        })
        assert status == 401
        assert body["error"] == "family_revoked"
    finally:
        server.shutdown()
