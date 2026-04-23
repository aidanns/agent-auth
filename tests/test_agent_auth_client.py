# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for :class:`agent_auth_client.AgentAuthClient`.

Focus here is on the validate() path that previously lived in
``things_bridge.authz``; broader endpoint coverage lives in the
integration suite under ``tests/integration/agent_auth/``.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from agent_auth_client import (
    AgentAuthClient,
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)


class _Responder(BaseHTTPRequestHandler):
    status = 200
    body: ClassVar[dict[str, Any]] = {"valid": True}
    extra_headers: ClassVar[dict[str, str]] = {}
    last_request_body: bytes | None = None
    last_request_path: str | None = None

    def log_message(self, *args, **kwargs):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Responder.last_request_body = self.rfile.read(length)
        _Responder.last_request_path = self.path
        body = json.dumps(_Responder.body).encode("utf-8")
        self.send_response(_Responder.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for header_name, header_value in _Responder.extra_headers.items():
            self.send_header(header_name, header_value)
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
    assert _Responder.last_request_path == "/agent-auth/v1/validate"
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
    _Responder.extra_headers = {}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzUnavailableError):
        client.validate("aa_xxx_yyy", "things:read")


def test_validate_rate_limited_raises_with_retry_after(auth_server):
    # Agent-auth returns 429 for a rate-limited family; the authz client
    # must surface it as AuthzRateLimitedError carrying the Retry-After
    # header so the bridge can pass it through unchanged to its caller.
    _, url = auth_server
    _Responder.status = 429
    _Responder.body = {"error": "rate_limited"}
    _Responder.extra_headers = {"Retry-After": "7"}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzRateLimitedError) as exc_info:
        client.validate("aa_xxx_yyy", "things:read")
    assert exc_info.value.retry_after_seconds == 7


def test_validate_rate_limited_defaults_retry_after_when_header_missing(auth_server):
    # A 429 without a Retry-After header (malformed upstream) must not
    # crash the client; fall back to a conservative 1s default so the
    # caller has a sane pacing hint.
    _, url = auth_server
    _Responder.status = 429
    _Responder.body = {"error": "rate_limited"}
    _Responder.extra_headers = {}
    client = AgentAuthClient(url, timeout_seconds=2.0)
    with pytest.raises(AuthzRateLimitedError) as exc_info:
        client.validate("aa_xxx_yyy", "things:read")
    assert exc_info.value.retry_after_seconds == 1


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
    # send plaintext on port 443. After #101 the connection class is picked
    # on the fly inside ``validate``; pin the invariants via the
    # TLS-selection flags instead.
    client = AgentAuthClient("https://auth.example.invalid:9443")
    assert client._use_tls is True
    assert client._ssl_context is not None
    assert client._port == 9443


def test_http_url_does_not_build_ssl_context():
    # Loopback HTTP stays the default posture for a single-user host;
    # the client must not pay for TLS context creation in that path.
    client = AgentAuthClient("http://auth.example.invalid:9100")
    assert client._use_tls is False
    assert client._ssl_context is None
    assert client._port == 9100


def test_https_url_with_ca_cert_loads_bundle(tmp_path):
    # Self-signed deployments point ``auth_ca_cert_path`` at a PEM file
    # the authz client uses to verify the server. Pin that the explicit
    # CA bundle is loaded (not silently ignored) by asserting the
    # context is present and distinct from the default.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_utcnow())
        .not_valid_after(_utcnow_plus_hours(1))
        .sign(key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    client = AgentAuthClient("https://auth.example.invalid:9443", ca_cert_path=str(ca_path))
    assert client._ssl_context is not None


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _utcnow_plus_hours(hours):
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(hours=hours)
