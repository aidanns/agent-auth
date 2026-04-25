# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""TLS-mode tests for the ``AgentAuthServer`` HTTP listener.

Pins the SC-8 posture documented in ``SECURITY.md``: when both
``tls_cert_path`` and ``tls_key_path`` are set, the server speaks TLS
on the bound socket and plaintext HTTP clients are refused. ADR 0025
captures the decision.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import urllib.error
import urllib.request
from http.client import HTTPConnection, HTTPSConnection

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.metrics import build_registry
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests_support.tls import generate_self_signed_cert


def _issue_health_token(server, store):
    family_id = "fam-tls-test"
    store.create_family(family_id, {"agent-auth:health": "allow"})
    access_token, _ = create_token_pair(server.signing_key, store, family_id, server.config)
    return access_token


@pytest.fixture
def tls_server(tmp_path, tmp_dir, signing_key, encryption_key):
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
        tls_cert_path=str(cert_path),
        tls_key_path=str(key_path),
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    # TLS tests never reach the approval path; empty URL = deny closed.
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "server": server,
            "port": port,
            "store": store,
            "cert_path": cert_path,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_tls_server_accepts_https_request_with_pinned_ca(tls_server):
    # Positive path: a client that trusts the self-signed cert completes
    # a TLS handshake and gets a 200 from /health.
    token = _issue_health_token(tls_server["server"], tls_server["store"])
    ctx = ssl.create_default_context(cafile=str(tls_server["cert_path"]))
    conn = HTTPSConnection("127.0.0.1", tls_server["port"], timeout=5, context=ctx)
    try:
        conn.request(
            "GET",
            "/agent-auth/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = conn.getresponse()
        body = response.read()
    finally:
        conn.close()
    assert response.status == 200
    assert json.loads(body) == {"status": "ok"}


def test_tls_server_rejects_plaintext_http_client(tls_server):
    # Regression: a plaintext HTTP request to a TLS-wrapped socket
    # must not leak data as a 400 response body; the connection is
    # killed at handshake time. Assert we surface a transport-level
    # failure rather than a semantic HTTP status.
    conn = HTTPConnection("127.0.0.1", tls_server["port"], timeout=5)
    try:
        conn.request("GET", "/agent-auth/health")
        with pytest.raises((ConnectionError, OSError, urllib.error.URLError)):
            conn.getresponse().read()
    finally:
        conn.close()


def test_tls_server_rejects_client_without_trust_bundle(tls_server):
    # A client that does not trust the self-signed CA must fail the
    # handshake — verifies we are not accidentally shipping a
    # ``check_hostname=False`` context or disabling verification.
    ctx = ssl.create_default_context()  # system roots only; won't include our CA
    conn = HTTPSConnection("127.0.0.1", tls_server["port"], timeout=5, context=ctx)
    try:
        with pytest.raises(ssl.SSLError):
            conn.request("GET", "/agent-auth/health")
            conn.getresponse()
    finally:
        conn.close()


def test_config_rejects_half_configured_tls_pair(tmp_path):
    # A missing key when cert is set (or vice versa) must fail loudly
    # at Config construction. Silent fall-through to plaintext would
    # be exactly the SC-8 regression the field exists to prevent.
    with pytest.raises(ValueError):
        Config(tls_cert_path=str(tmp_path / "cert.pem"))
    with pytest.raises(ValueError):
        Config(tls_key_path=str(tmp_path / "key.pem"))
