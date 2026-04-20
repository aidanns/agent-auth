# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the things-bridge authz client."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from things_bridge.authz import AgentAuthClient
from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)


class _Responder(BaseHTTPRequestHandler):
    status = 200
    body: ClassVar[dict] = {"valid": True}
    last_request_body: bytes | None = None

    def log_message(self, *args, **kwargs):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Responder.last_request_body = self.rfile.read(length)
        body = json.dumps(_Responder.body).encode("utf-8")
        self.send_response(_Responder.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def auth_server():
    server = HTTPServer(("127.0.0.1", 0), _Responder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_validate_allows_on_success(auth_server):
    _server, url = auth_server
    _Responder.status = 200
    _Responder.body = {"valid": True}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    client.validate("aa_xxx_yyy", "things:read", description="list todos")
    assert _Responder.last_request_body is not None
    sent = json.loads(_Responder.last_request_body)
    assert sent["token"] == "aa_xxx_yyy"
    assert sent["required_scope"] == "things:read"
    assert sent["description"] == "list todos"


def test_validate_token_expired_raises(auth_server):
    _, url = auth_server
    _Responder.status = 401
    _Responder.body = {"valid": False, "error": "token_expired"}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzTokenExpiredError):
        client.validate("aa_xxx_yyy", "things:read")


def test_validate_invalid_token_raises(auth_server):
    _, url = auth_server
    _Responder.status = 401
    _Responder.body = {"valid": False, "error": "invalid_token"}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzTokenInvalidError):
        client.validate("aa_xxx_yyy", "things:read")


def test_validate_scope_denied_raises(auth_server):
    _, url = auth_server
    _Responder.status = 403
    _Responder.body = {"valid": False, "error": "scope_denied"}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzScopeDeniedError):
        client.validate("aa_xxx_yyy", "things:read")


def test_validate_unexpected_status_raises_unavailable(auth_server):
    _, url = auth_server
    _Responder.status = 502
    _Responder.body = {"error": "bad_gateway"}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzUnavailableError):
        client.validate("aa_xxx_yyy", "things:read")


def test_validate_unreachable_raises_unavailable():
    # Port 1 is typically unreachable and will connection-refuse quickly.
    client = AgentAuthClient("http://127.0.0.1:1", timeout_seconds=1.0)
    with pytest.raises(AuthzUnavailableError):
        client.validate("aa_xxx_yyy", "things:read")


def test_invalid_auth_url_raises_valueerror():
    with pytest.raises(ValueError):
        AgentAuthClient("not-a-url")


def test_https_url_uses_https_connection():
    # Regression: the client previously used HTTPConnection regardless of
    # scheme, so any deployment that put agent-auth behind TLS would silently
    # send plaintext on port 443.
    from http.client import HTTPSConnection

    client = AgentAuthClient("https://auth.example.invalid:9443")
    assert client._conn_cls is HTTPSConnection
    assert client._port == 9443
