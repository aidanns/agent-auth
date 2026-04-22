# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""TLS-mode tests for the ``ThingsBridgeServer`` HTTP listener.

Mirrors ``tests/test_server_tls.py`` for agent-auth — pins the SC-8
posture that the bridge uses the same TLS pattern when
``tls_cert_path`` / ``tls_key_path`` are configured.
"""

from __future__ import annotations

import json
import ssl
import threading
from http.client import HTTPConnection, HTTPSConnection

import pytest

from tests._tls import generate_self_signed_cert
from tests.things_client_fake.store import FakeThingsClient, FakeThingsStore
from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config
from things_bridge.metrics import build_registry as build_bridge_registry
from things_bridge.server import ThingsBridgeServer


class _AcceptAuthz(AgentAuthClient):
    """Trivial stand-in that accepts any token without network I/O."""

    def __init__(self):
        super().__init__("http://test-fake")

    def validate(self, token, required_scope, *, description=None):
        return


@pytest.fixture
def tls_bridge(tmp_path):
    cert_path, key_path = generate_self_signed_cert(tmp_path)
    config = Config(
        host="127.0.0.1",
        port=0,
        tls_cert_path=str(cert_path),
        tls_key_path=str(key_path),
    )
    store = FakeThingsStore()
    things = FakeThingsClient(store)
    authz = _AcceptAuthz()
    registry, metrics = build_bridge_registry()
    server = ThingsBridgeServer(config, things, authz, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"port": port, "cert_path": cert_path, "server": server}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_tls_bridge_accepts_https_request_with_pinned_ca(tls_bridge):
    # Positive path: trusted self-signed cert → /health returns 200.
    ctx = ssl.create_default_context(cafile=str(tls_bridge["cert_path"]))
    conn = HTTPSConnection("127.0.0.1", tls_bridge["port"], timeout=5, context=ctx)
    try:
        conn.request(
            "GET",
            "/things-bridge/health",
            headers={"Authorization": "Bearer dummy"},
        )
        response = conn.getresponse()
        body = response.read()
    finally:
        conn.close()
    assert response.status == 200
    assert json.loads(body) == {"status": "ok"}


def test_tls_bridge_rejects_plaintext_http_client(tls_bridge):
    conn = HTTPConnection("127.0.0.1", tls_bridge["port"], timeout=5)
    try:
        conn.request("GET", "/things-bridge/health")
        with pytest.raises((ConnectionError, OSError)):
            conn.getresponse().read()
    finally:
        conn.close()


def test_config_rejects_half_configured_tls_pair(tmp_path):
    with pytest.raises(ValueError):
        Config(tls_cert_path=str(tmp_path / "cert.pem"))
    with pytest.raises(ValueError):
        Config(tls_key_path=str(tmp_path / "key.pem"))
