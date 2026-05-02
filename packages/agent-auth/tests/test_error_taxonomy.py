# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the agent-auth half of the error-code taxonomy.

The error taxonomy is split across two packages — agent-auth's response
codes are exercised here, and things-bridge's response codes are
exercised in
``packages/things-bridge/tests/test_things_bridge_error_taxonomy.py``.
The split keeps each package's unit-test shard self-contained (the
bridge tests need ``things_client_fake``, which is shipped under
``packages/things-bridge/tests/`` as a test-only fake and is not on the
agent-auth shard's pythonpath).

Every error code documented in ``design/error-codes.md`` is exercised by
exactly one of the two files. Each test triggers the precise condition
that should produce a given code and asserts the response body. Changes
to error strings or HTTP statuses will fail these tests, which is the
intent: the error taxonomy is public API.

Documented codes covered here
-----------------------------
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
  not_found (404), rate_limited (429).
"""

import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.metrics import build_registry as build_auth_registry
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests_support.http import get, post

# -- test infrastructure --


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
    # Error-taxonomy tests exercise 400/401/403/404 paths; the notifier
    # is only reached on prompt-tier approvals, which these tests don't
    # cover. Fail-closed client keeps the fixture deterministic.
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
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


def test_agent_auth_rate_limited(tmp_dir, signing_key, encryption_key):
    # Spin up a server with a tiny 1-request-per-minute budget so the
    # taxonomy-coverage gate has a 429 call site without needing to
    # hammer the default-rate limiter.
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
        rate_limit_per_minute=1,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    # Rate-limit test never hits the approval path; empty notifier URL
    # denies closed without opening a socket.
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_auth_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        family_id = "fam-rl-tax"
        store.create_family(family_id, {"agent-auth:health": "allow"})
        access_token, _ = create_token_pair(signing_key, store, family_id, config)
        headers = _bearer(access_token)
        # First call drains the bucket; the second lands on 429.
        status, _ = get(f"http://127.0.0.1:{port}/agent-auth/health", headers)
        assert status == 200
        status, body = get(f"http://127.0.0.1:{port}/agent-auth/health", headers)
        assert status == 429
        assert body["error"] == "rate_limited"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
