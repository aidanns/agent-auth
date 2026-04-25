# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the gpg-cli BridgeClient HTTP + refresh / reissue flow.

Dual-handler test server: one port simulates gpg-bridge's
``/gpg-bridge/v1/sign`` endpoint, the other simulates agent-auth's
``/agent-auth/v1/token/{refresh,reissue}`` endpoints. This drives the
full retry loop end-to-end without mocking internal classes.

Mirrors the layout of ``packages/things-cli/tests/test_things_cli_client.py``.
The persistence-after-retry-failure case (``test_only_one_retry_on_persistent_401``)
asserts the load-bearing safety property from ADR 0011 — refresh tokens
are single-use, so the rotated pair must be persisted *before* the
retried request runs.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from gpg_cli.client import BridgeClient
from gpg_cli.config import Credentials, FileStore
from gpg_cli.errors import (
    BridgeForbiddenError,
    BridgeRateLimitedError,
    BridgeTokenExpiredError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
)
from gpg_models.models import SignRequest

# -- Fake servers --


class _BridgeHandler(BaseHTTPRequestHandler):
    """Driven by class-level state so tests can queue per-request responses."""

    queued_responses: ClassVar[list[tuple[int, dict[str, Any] | None, str | None]]] = []
    captured_requests: ClassVar[list[tuple[str, str, str | None, bytes]]] = []

    def log_message(self, *args, **kwargs):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        token = self._bearer()
        _BridgeHandler.captured_requests.append(("POST", self.path, token, body))
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
    """Simulates agent-auth's token rotation endpoints."""

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


def _make_client(
    urls, tmp_path, *, family_id: str | None = "fam-1"
) -> tuple[BridgeClient, FileStore]:
    store = FileStore(str(tmp_path / "config.yaml"))
    creds = Credentials(
        access_token="aa_initial",
        refresh_token="rt_initial",
        auth_url=urls["auth_url"],
        family_id=family_id,
    )
    store.save(creds)
    client = BridgeClient(
        creds,
        store,
        bridge_url=urls["bridge_url"],
        timeout_seconds=2.0,
    )
    return client, store


def _sign_request() -> SignRequest:
    """Trivial sign request so the test bodies stay focused on auth flow."""
    return SignRequest(
        local_user="0xKEY",
        payload=b"hello",
        armor=True,
        status_fd_enabled=False,
        keyid_format="long",
    )


def _sign_response(signature: bytes = b"sig-bytes") -> dict[str, Any]:
    return {
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "status_text": "",
    }


def test_sign_returns_parsed_result(servers, tmp_path):
    _BridgeHandler.queued_responses = [(200, _sign_response(b"sig-1"), "aa_initial")]
    client, _ = _make_client(servers, tmp_path)
    result = client.sign(_sign_request())
    assert result.signature == b"sig-1"


@pytest.mark.covers_function("Auto Refresh Token")
def test_401_token_expired_triggers_refresh_and_retry(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
        (200, _sign_response(b"sig-after-refresh"), "aa_new"),
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
    result = client.sign(_sign_request())
    assert result.signature == b"sig-after-refresh"
    # Credentials rolled forward and persisted.
    loaded = store.load()
    assert loaded.access_token == "aa_new"
    assert loaded.refresh_token == "rt_new"


@pytest.mark.covers_function("Auto Refresh Token")
def test_refresh_expired_triggers_reissue_and_retry(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
        (200, _sign_response(b"sig-reissued"), "aa_reissued"),
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
    result = client.sign(_sign_request())
    assert result.signature == b"sig-reissued"
    loaded = store.load()
    assert loaded.access_token == "aa_reissued"
    assert loaded.refresh_token == "rt_reissued"


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
        client.sign(_sign_request())


def test_reuse_detected_raises_unauthorized(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "refresh_token_reuse_detected"}),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError):
        client.sign(_sign_request())


def test_family_revoked_raises_unauthorized(servers, tmp_path):
    _BridgeHandler.queued_responses = [
        (401, {"error": "token_expired"}, "aa_initial"),
    ]
    _AuthHandler.refresh_responses = [
        (401, {"error": "family_revoked"}),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError, match="family_revoked"):
        client.sign(_sign_request())


def test_403_surfaces_as_forbidden(servers, tmp_path):
    _BridgeHandler.queued_responses = [(403, {"error": "scope_denied"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeForbiddenError):
        client.sign(_sign_request())


def test_429_surfaces_as_rate_limited(servers, tmp_path):
    _BridgeHandler.queued_responses = [(429, {"error": "rate_limited"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeRateLimitedError):
        client.sign(_sign_request())


def test_502_surfaces_as_unavailable(servers, tmp_path):
    _BridgeHandler.queued_responses = [(502, {"error": "gpg_unavailable"}, None)]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnavailableError):
        client.sign(_sign_request())


@pytest.mark.covers_function("Auto Refresh Token")
def test_only_one_retry_on_persistent_401(servers, tmp_path):
    """The retry budget is exactly one — and the rotated pair persists across failure.

    Refresh tokens are single-use (ADR 0011); the new pair must be on
    disk *before* the retried request runs so a crash between the
    refresh response and the retry doesn't leave a consumed refresh
    token in the file. Modelled on
    ``packages/things-cli/tests/test_things_cli_client.py::test_only_one_retry_on_persistent_401``.
    """
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
        client.sign(_sign_request())
    # Retry budget honoured — exactly two calls to the bridge.
    assert len(_BridgeHandler.captured_requests) == 2
    # Load-bearing assertion: the new pair is on disk despite the
    # retried call failing.
    loaded = store.load()
    assert loaded.access_token == "aa_new"
    assert loaded.refresh_token == "rt_new"


def test_no_family_id_blocks_reissue(servers, tmp_path):
    _BridgeHandler.queued_responses = [(401, {"error": "token_expired"}, "aa_initial")]
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_expired"})]
    client, _ = _make_client(servers, tmp_path, family_id=None)
    with pytest.raises(BridgeUnauthorizedError, match="setup-devcontainer-signing.sh"):
        client.sign(_sign_request())


def test_token_expired_distinct_from_generic_unauthorized(servers, tmp_path):
    """The first call surfaces ``BridgeTokenExpiredError`` only when ``error == 'token_expired'``.

    A 401 with a non-``token_expired`` body code skips the refresh path
    and raises plain :class:`BridgeUnauthorizedError`. This prevents
    the retry loop from chasing an expensive refresh on a body-shape
    that didn't ask for it.
    """
    _BridgeHandler.queued_responses = [
        (401, {"error": "invalid_token"}, "aa_initial"),
    ]
    client, _ = _make_client(servers, tmp_path)
    with pytest.raises(BridgeUnauthorizedError) as exc_info:
        client.sign(_sign_request())
    # Specifically NOT a BridgeTokenExpiredError — that subclass is
    # reserved for the body code that drives the refresh path.
    assert not isinstance(exc_info.value, BridgeTokenExpiredError)
    # The auth server must not have been called at all.
    assert _AuthHandler.captured_requests == []
