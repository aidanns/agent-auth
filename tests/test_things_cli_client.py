# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the things-cli BridgeClient HTTP flow.

Uses a dual-handler test server: one port simulates the bridge, another simulates
agent-auth's token endpoints. This lets us drive the full refresh/reissue logic
without mocking internal classes.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from things_cli.client import BridgeClient
from things_cli.credentials import Credentials, FileStore
from things_cli.errors import (
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
)

# -- Fake bridge --


class _BridgeHandler(BaseHTTPRequestHandler):
    """Driven by module-level config dict so tests can set responses per request."""

    queued_responses: ClassVar[list[tuple[int, dict[str, Any] | None, str | None]]] = []
    captured_requests: ClassVar[list[tuple[str, str, str | None, bytes]]] = []

    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        token = self._bearer()
        _BridgeHandler.captured_requests.append(("GET", self.path, token, body))
        status, resp_body, expect_token = _BridgeHandler.queued_responses.pop(0)
        if expect_token is not None:
            assert token == expect_token, f"Expected token {expect_token!r}, got {token!r}"
        self._send(status, resp_body)

    def _bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:]
        return None

    def _send(self, status, body):
        body_bytes = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if body_bytes:
            self.wfile.write(body_bytes)


class _AuthHandler(BaseHTTPRequestHandler):
    """Simulates agent-auth token endpoints."""

    refresh_responses: ClassVar[list[tuple[int, dict[str, Any]]]] = []
    reissue_responses: ClassVar[list[tuple[int, dict[str, Any]]]] = []
    captured_requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []

    def log_message(self, *args, **kwargs):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}
        _AuthHandler.captured_requests.append((self.path, body))
        if self.path == "/agent-auth/v1/token/refresh":
            status, resp = _AuthHandler.refresh_responses.pop(0)
        elif self.path == "/agent-auth/v1/token/reissue":
            status, resp = _AuthHandler.reissue_responses.pop(0)
        else:
            status, resp = 404, {"error": "not_found"}
        out = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def servers():
    _BridgeHandler.queued_responses = []
    _BridgeHandler.captured_requests = []
    _AuthHandler.refresh_responses = []
    _AuthHandler.reissue_responses = []
    _AuthHandler.captured_requests = []

    bridge = HTTPServer(("127.0.0.1", 0), _BridgeHandler)
    auth = HTTPServer(("127.0.0.1", 0), _AuthHandler)
    t1 = threading.Thread(target=bridge.serve_forever, daemon=True)
    t2 = threading.Thread(target=auth.serve_forever, daemon=True)
    t1.start()
    t2.start()
    yield {
        "bridge_url": f"http://127.0.0.1:{bridge.server_address[1]}",
        "auth_url": f"http://127.0.0.1:{auth.server_address[1]}",
    }
    bridge.shutdown()
    auth.shutdown()


def _make_client(urls, tmp_path) -> tuple[BridgeClient, FileStore]:
    store = FileStore(str(tmp_path / "c.json"))
    creds = Credentials(
        access_token="aa_initial",
        refresh_token="rt_initial",
        bridge_url=urls["bridge_url"],
        auth_url=urls["auth_url"],
        family_id="fam-1",
    )
    store.save(creds)
    return BridgeClient(creds, store, timeout_seconds=2.0), store


def test_get_returns_parsed_body(servers, tmp_path):
    _BridgeHandler.queued_responses = [(200, {"todos": []}, "aa_initial")]
    client, _ = _make_client(servers, tmp_path)
    result = client.list_todos()
    assert result == {"todos": []}


@pytest.mark.covers_function("Auto Refresh Token")
def test_401_token_expired_triggers_refresh_and_retry(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
        (200, {"todos": [{"id": "t1"}]}, "aa_new"),
    ]
    _AuthHandler.refresh_responses = [
        (
            200,
            {
                "access_token": "aa_new",
                "refresh_token": "rt_new",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    client, store = _make_client(servers, tmp_path)
    result = client.list_todos()
    assert result == {"todos": [{"id": "t1"}]}
    # Credentials rolled forward and persisted.
    loaded = store.load()
    assert loaded.access_token == "aa_new"
    assert loaded.refresh_token == "rt_new"


@pytest.mark.covers_function("Auto Refresh Token")
def test_refresh_expired_triggers_reissue_and_retry(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
        (200, {"todos": []}, "aa_reissued"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "refresh_token_expired"}),
    ]
    _AuthHandler.reissue_responses = [
        (
            200,
            {
                "access_token": "aa_reissued",
                "refresh_token": "rt_reissued",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    client, store = _make_client(servers, tmp_path)
    result = client.list_todos()
    assert result == {"todos": []}
    assert store.load().access_token == "aa_reissued"


def test_reissue_denied_raises_unauthorized(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "refresh_token_expired"}),
    ]
    _AuthHandler.reissue_responses = [
        (403, {"error": "reissue_denied"}),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError):
        client.list_todos()


def test_reuse_detected_raises_unauthorized(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "refresh_token_reuse_detected"}),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError):
        client.list_todos()


def test_403_surfaces_as_forbidden(servers, tmp_path):
    _BridgeHandler.queued_responses = [(403, {"error": "scope_denied"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeForbiddenError):
        client.list_todos()


def test_404_surfaces_as_not_found(servers, tmp_path):
    _BridgeHandler.queued_responses = [(404, {"error": "not_found"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeNotFoundError):
        client.get_todo("unknown")


def test_502_surfaces_as_unavailable(servers, tmp_path):
    _BridgeHandler.queued_responses = [(502, {"error": "things_unavailable"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnavailableError):
        client.list_todos()


def test_only_one_retry_on_persistent_401(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
        (401, {"error": "token_expired"}, "aa_new"),
    ]
    _AuthHandler.refresh_responses = [
        (
            200,
            {
                "access_token": "aa_new",
                "refresh_token": "rt_new",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    client, store = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError):
        client.list_todos()
    # Ensure we stopped after the second call (no infinite loop).
    assert len(_BridgeHandler.captured_requests) == 2
    # Refresh tokens are single-use; the new pair must be persisted even when
    # the retry fails, otherwise the next run starts with a consumed refresh
    # token and the whole family gets revoked on next use.
    loaded = store.load()
    assert loaded.access_token == "aa_new"
    assert loaded.refresh_token == "rt_new"


def test_query_params_are_sent(servers, tmp_path):
    _BridgeHandler.queued_responses = [(200, {"todos": []}, None)]
    client, _ = _make_client(servers, tmp_path)
    client.list_todos(params={"status": "open", "project": "p1"})
    [(_, path, _, _)] = _BridgeHandler.captured_requests
    assert "status=open" in path
    assert "project=p1" in path


def test_empty_2xx_body_raises_unavailable(servers, tmp_path):
    # The bridge always returns a JSON body. If some proxy ever strips it
    # and returns an empty 2xx, callers would crash trying to `.get()` on
    # None — surface it as a typed error instead.
    _BridgeHandler.queued_responses = [(200, None, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnavailableError):
        client.list_todos()


def test_reissue_403_preserves_server_error_code(servers, tmp_path):
    # A 403 from /reissue should surface the server-provided error code
    # verbatim (e.g. "reissue_denied", "family_revoked") rather than
    # silently masking it with a hard-coded label — the user needs the
    # specific code to know whether to retry or re-login.
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "refresh_token_expired"}),
    ]
    _AuthHandler.reissue_responses = [
        (403, {"error": "family_revoked"}),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError, match="family_revoked"):
        client.list_todos()


def test_no_family_id_blocks_reissue(servers, tmp_path):
    _BridgeHandler.queued_responses = [(401, {"error": "token_expired"}, "aa_initial")]
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_expired"})]
    store = FileStore(str(tmp_path / "c.json"))
    creds = Credentials(
        access_token="aa_initial",
        refresh_token="rt_initial",
        bridge_url=servers["bridge_url"],
        auth_url=servers["auth_url"],
        family_id=None,
    )
    store.save(creds)
    client = BridgeClient(creds, store, timeout_seconds=2.0)
    with pytest.raises(BridgeUnauthorizedError):
        client.list_todos()
