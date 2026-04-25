# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: agent-auth subsystem returns 5xx or is unreachable.

The bridge must fail CLOSED on every authz failure mode — a 5xx
response from agent-auth, a hung agent-auth, a malformed JSON body,
or a connection refused. Failing open (signing requests when authz
cannot make a decision) would defeat the entire authorization model
and is the most damaging fault category in this service.
"""

from __future__ import annotations

import base64
import contextlib
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.errors import AuthzUnavailableError
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer

FIXTURE = {
    "keys": [
        {
            "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
            "user_ids": ["Test Key <test@example.invalid>"],
            "aliases": ["0xCDEF1234567890AB", "test@example.invalid"],
        }
    ],
}


class _ServerHandle:
    def __init__(self, server: GpgBridgeServer, thread: threading.Thread, port: int):
        self.server = server
        self.thread = thread
        self.port = port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5.0)


@pytest.fixture
def fixture_path(tmp_path: Path) -> str:
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(FIXTURE))
    return str(path)


@pytest.fixture
def gpg_client(fixture_path: str) -> GpgSubprocessClient:
    return GpgSubprocessClient(
        command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", fixture_path],
        timeout_seconds=15.0,
    )


def _start_bridge(authz: AgentAuthClient, gpg_client: GpgSubprocessClient) -> _ServerHandle:
    config = Config(port=0)
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg_client, authz, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _ServerHandle(server, thread, port)


def _post_sign(url: str, *, token: str = "valid-token") -> tuple[int, dict[str, Any]]:
    body = json.dumps(
        {
            "local_user": "test@example.invalid",
            "payload_b64": base64.b64encode(b"x").decode("ascii"),
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


def _pick_closed_port() -> int:
    """Bind an ephemeral port and immediately release it.

    The kernel will not hand the same port out again for a short
    window, so a connect attempt to it returns ECONNREFUSED — the
    cleanest way to model "agent-auth is dead".
    """
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.covers_function("Authorize Sign Request")
def test_authz_connection_refused_fails_closed(gpg_client: GpgSubprocessClient) -> None:
    """When agent-auth is unreachable the bridge must reply 502, NOT sign.

    The only way to be sure the request was denied is to assert the
    backend was never invoked — the bridge config above uses the
    fake fixture, so a successful sign would return ``exit_code: 0``
    with a real signature. We assert neither.
    """
    authz = AgentAuthClient(f"http://127.0.0.1:{_pick_closed_port()}", timeout_seconds=1.0)
    handle = _start_bridge(authz, gpg_client)
    try:
        status, body = _post_sign(f"{handle.base_url}/gpg-bridge/v1/sign")
        assert status == 502
        assert body == {"error": "authz_unavailable"}
    finally:
        handle.close()


def _start_authz_5xx(status_code: int) -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    """Run a stub agent-auth that always answers with the given status code."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = b'{"error": "internal"}'
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}", server, thread


@pytest.mark.covers_function("Authorize Sign Request")
def test_authz_500_fails_closed(gpg_client: GpgSubprocessClient) -> None:
    """A 500 from agent-auth must surface as 502 from the bridge — never as a sign success."""
    authz_url, authz_server, authz_thread = _start_authz_5xx(500)
    try:
        authz = AgentAuthClient(authz_url, timeout_seconds=2.0)
        handle = _start_bridge(authz, gpg_client)
        try:
            status, body = _post_sign(f"{handle.base_url}/gpg-bridge/v1/sign")
            assert status == 502
            assert body == {"error": "authz_unavailable"}
        finally:
            handle.close()
    finally:
        authz_server.shutdown()
        authz_server.server_close()
        authz_thread.join(timeout=2.0)


@pytest.mark.covers_function("Authorize Sign Request")
def test_authz_503_fails_closed(gpg_client: GpgSubprocessClient) -> None:
    """A 503 (agent-auth unavailable) must NOT translate into a green sign."""
    authz_url, authz_server, authz_thread = _start_authz_5xx(503)
    try:
        authz = AgentAuthClient(authz_url, timeout_seconds=2.0)
        handle = _start_bridge(authz, gpg_client)
        try:
            status, body = _post_sign(f"{handle.base_url}/gpg-bridge/v1/sign")
            assert status == 502
            assert body == {"error": "authz_unavailable"}
        finally:
            handle.close()
    finally:
        authz_server.shutdown()
        authz_server.server_close()
        authz_thread.join(timeout=2.0)


def _start_authz_hang() -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    """Run a stub agent-auth that sleeps past the client timeout."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            time.sleep(5.0)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}", server, thread


@pytest.mark.covers_function("Authorize Sign Request")
def test_authz_read_timeout_fails_closed(gpg_client: GpgSubprocessClient) -> None:
    """An agent-auth that hangs past the client deadline fails closed.

    The authz client wraps the timeout into ``AuthzUnavailableError``,
    which the bridge's ``_validate`` translates into a 502 — same
    surface as a connection refused. Without this the bridge could
    hang the request thread forever waiting on a wedged authz.
    """
    authz_url, authz_server, authz_thread = _start_authz_hang()
    try:
        authz = AgentAuthClient(authz_url, timeout_seconds=0.3)
        handle = _start_bridge(authz, gpg_client)
        try:
            status, body = _post_sign(f"{handle.base_url}/gpg-bridge/v1/sign")
            assert status == 502
            assert body == {"error": "authz_unavailable"}
        finally:
            handle.close()
    finally:
        authz_server.shutdown()
        authz_server.server_close()
        authz_thread.join(timeout=2.0)


def _start_authz_garbage() -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    """Run a stub agent-auth that returns 200 with non-JSON bytes."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = b"<html><body>nope</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}", server, thread


@pytest.mark.covers_function("Authorize Sign Request")
def test_authz_non_json_response_fails_closed(gpg_client: GpgSubprocessClient) -> None:
    """A 200-OK with a non-JSON body must not be parsed as a valid grant.

    The fail-closed contract says the bridge can only sign on a clean
    ``{"valid": true}`` envelope from agent-auth. A reverse proxy
    returning an HTML error page on the validate path must surface as
    a 502, not a green sign.
    """
    authz_url, authz_server, authz_thread = _start_authz_garbage()
    try:
        authz = AgentAuthClient(authz_url, timeout_seconds=2.0)
        # Confirm the client itself rejects the response.
        with pytest.raises(AuthzUnavailableError):
            authz.validate("aa_test", "gpg:sign")
        # Now confirm the bridge translates that into 502.
        handle = _start_bridge(authz, gpg_client)
        try:
            status, body = _post_sign(f"{handle.base_url}/gpg-bridge/v1/sign")
            assert status == 502
            assert body == {"error": "authz_unavailable"}
        finally:
            handle.close()
    finally:
        authz_server.shutdown()
        authz_server.server_close()
        authz_thread.join(timeout=2.0)
