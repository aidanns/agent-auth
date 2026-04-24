# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for :class:`things_bridge_client.ThingsBridgeClient`.

Integration coverage under ``tests/integration/things_bridge/`` already
drives the full happy path through a live bridge container. This unit
suite pins the error-mapping contract against a stub HTTP server so a
regression in one of the status-code-to-exception branches doesn't
require a Docker run to be caught.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from things_bridge_client import (
    ThingsBridgeClient,
    ThingsBridgeForbiddenError,
    ThingsBridgeNotFoundError,
    ThingsBridgeRateLimitedError,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)
from things_models.models import TodoId


class _StubHandler(BaseHTTPRequestHandler):
    status = 200
    body: ClassVar[Any] = {"todos": []}
    content_type = "application/json"
    extra_headers: ClassVar[dict[str, str]] = {}
    last_path: str | None = None
    last_bearer: str | None = None

    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        _StubHandler.last_path = self.path
        header = self.headers.get("Authorization", "")
        _StubHandler.last_bearer = header[7:] if header.startswith("Bearer ") else None
        if isinstance(_StubHandler.body, dict | list):
            body = json.dumps(_StubHandler.body).encode("utf-8")
        else:
            body = str(_StubHandler.body).encode("utf-8")
        self.send_response(_StubHandler.status)
        self.send_header("Content-Type", _StubHandler.content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in _StubHandler.extra_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def bridge_server():
    _StubHandler.status = 200
    _StubHandler.body = {"todos": []}
    _StubHandler.content_type = "application/json"
    _StubHandler.extra_headers = {}
    _StubHandler.last_path = None
    _StubHandler.last_bearer = None
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_list_todos_sends_bearer_and_returns_body(bridge_server):
    _server, url = bridge_server
    _StubHandler.body = {"todos": [{"id": "t1"}]}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    result = client.list_todos("aa_abc")
    assert result == {"todos": [{"id": "t1"}]}
    assert _StubHandler.last_path == "/things-bridge/v1/todos"
    assert _StubHandler.last_bearer == "aa_abc"


def test_list_todos_with_params_encodes_query(bridge_server):
    _server, url = bridge_server
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    client.list_todos("aa_abc", params={"status": "open", "project": "p1"})
    assert _StubHandler.last_path is not None
    assert "status=open" in _StubHandler.last_path
    assert "project=p1" in _StubHandler.last_path


def test_missing_bearer_sends_no_authorization_header(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 401
    _StubHandler.body = {"error": "unauthorized"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeUnauthorizedError, match="unauthorized"):
        client.list_todos(None)
    assert _StubHandler.last_bearer is None


def test_401_token_expired_maps_to_token_expired(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 401
    _StubHandler.body = {"error": "token_expired"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeTokenExpiredError, match="token_expired"):
        client.list_todos("aa_abc")


def test_403_maps_to_forbidden(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 403
    _StubHandler.body = {"error": "scope_denied"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeForbiddenError, match="scope_denied"):
        client.get_todo("aa_abc", TodoId("t1"))


def test_404_maps_to_not_found(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 404
    _StubHandler.body = {"error": "not_found"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeNotFoundError, match="not_found"):
        client.get_todo("aa_abc", TodoId("missing"))


def test_429_surfaces_retry_after(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 429
    _StubHandler.body = {"error": "rate_limited"}
    _StubHandler.extra_headers = {"Retry-After": "5"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeRateLimitedError) as exc_info:
        client.list_todos("aa_abc")
    assert exc_info.value.retry_after_seconds == 5


def test_429_without_retry_after_defaults_to_one_second(bridge_server):
    # A missing/malformed Retry-After header must not crash the client;
    # fall back to a conservative 1s so callers have a sane pacing hint.
    _server, url = bridge_server
    _StubHandler.status = 429
    _StubHandler.body = {"error": "rate_limited"}
    _StubHandler.extra_headers = {}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeRateLimitedError) as exc_info:
        client.list_todos("aa_abc")
    assert exc_info.value.retry_after_seconds == 1


def test_502_maps_to_unavailable(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 502
    _StubHandler.body = {"error": "authz_unavailable"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeUnavailableError, match="authz_unavailable"):
        client.list_todos("aa_abc")


def test_empty_2xx_body_raises_unavailable(bridge_server):
    # The bridge always returns a JSON body; a proxy stripping it to an
    # empty 2xx would otherwise crash callers trying to `.get()` on None.
    _server, url = bridge_server
    _StubHandler.status = 200
    _StubHandler.body = ""
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeUnavailableError, match="empty body"):
        client.list_todos("aa_abc")


def test_connection_refused_raises_unavailable():
    # Port 1 is reserved; ECONNREFUSED must surface as typed unavailable.
    client = ThingsBridgeClient("http://127.0.0.1:1", timeout_seconds=1.0)
    with pytest.raises(ThingsBridgeUnavailableError, match="connection failed"):
        client.list_todos("aa_abc")


def test_invalid_base_url_raises_valueerror():
    with pytest.raises(ValueError):
        ThingsBridgeClient("not-a-url")


def test_https_url_uses_https_connection():
    client = ThingsBridgeClient("https://bridge.example.invalid:9443")
    assert client._use_tls is True
    assert client._ssl_context is not None
    assert client._port == 9443


def test_http_url_does_not_build_ssl_context():
    client = ThingsBridgeClient("http://bridge.example.invalid:9200")
    assert client._use_tls is False
    assert client._ssl_context is None


def test_check_health_returns_body_on_success(bridge_server):
    _server, url = bridge_server
    _StubHandler.body = {"status": "ok"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    assert client.check_health("aa_abc") == {"status": "ok"}


def test_check_health_503_raises_unavailable(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 503
    _StubHandler.body = {"status": "unhealthy"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeUnavailableError):
        client.check_health("aa_abc")


def test_get_metrics_text_returns_content_type_and_body(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 200
    _StubHandler.content_type = "text/plain"
    _StubHandler.body = "# HELP foo\nfoo 1\n"
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    content_type, body = client.get_metrics_text("aa_abc")
    assert content_type.startswith("text/plain")
    assert "foo 1" in body


def test_get_metrics_text_403_raises_forbidden(bridge_server):
    _server, url = bridge_server
    _StubHandler.status = 403
    _StubHandler.body = {"error": "scope_denied"}
    client = ThingsBridgeClient(url, timeout_seconds=2.0)
    with pytest.raises(ThingsBridgeForbiddenError):
        client.get_metrics_text("aa_abc")
