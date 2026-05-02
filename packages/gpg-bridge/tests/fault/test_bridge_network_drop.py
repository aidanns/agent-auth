# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: client drops the TCP connection mid-request.

The gpg-cli ↔ gpg-bridge hop runs over HTTPS. A devcontainer
restart, a tmux disconnect, or a flaky VPN can sever the socket
after the bearer has been read but before the response is written.
The bridge must:

1. NOT crash — the request handler must clean up cleanly.
2. NOT leak the in-flight backend subprocess.
3. Continue accepting new requests on the same listener.

These tests open a raw TCP socket against the bridge, write a
partial request, then close — and assert the next well-formed
request still succeeds.
"""

from __future__ import annotations

import base64
import json
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
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


class _FakeAuthz(AgentAuthClient):
    """In-memory authz client that never raises."""

    def __init__(self) -> None:
        super().__init__("http://test-fake")

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        return None


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


def _start_server(config: Config, gpg_client: GpgSubprocessClient) -> _ServerHandle:
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg_client, _FakeAuthz(), registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _ServerHandle(server, thread, port)


def _post_json(
    url: str, body: dict[str, Any], token: str = "valid-token"
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


@pytest.mark.covers_function("Serve GPG Bridge HTTP API")
def test_client_resets_mid_request_does_not_kill_server(
    gpg_client: GpgSubprocessClient,
) -> None:
    """A peer that hangs up mid-headers must not take the bridge down.

    Opens a raw socket, writes a half-formed request line, then
    closes — modelling a devcontainer process death after the bridge
    accepted the connection. The bridge's request thread must catch
    the resulting socket error, clean up, and the listener must keep
    serving.
    """
    config = Config(port=0)
    handle = _start_server(config, gpg_client)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", handle.port))
        # Partial HTTP request — POST line and one header, then close.
        # Without ``Content-Length`` the bridge sees the close as a
        # truncated request rather than EOF on the body.
        sock.sendall(b"POST /gpg-bridge/v1/sign HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        sock.close()
        # Brief settle so the bridge's handler thread observes the
        # half-close before we send the next request.
        time.sleep(0.1)
        # The server must still serve a normal request.
        status, body = _post_json(
            f"{handle.base_url}/gpg-bridge/v1/sign",
            {
                "local_user": "test@example.invalid",
                "payload_b64": base64.b64encode(b"after-drop").decode("ascii"),
                "armor": True,
            },
        )
        assert status == 200
        assert body["exit_code"] == 0
    finally:
        handle.close()


@pytest.mark.covers_function("Serve GPG Bridge HTTP API")
def test_client_resets_after_headers_does_not_kill_server(
    gpg_client: GpgSubprocessClient,
) -> None:
    """A peer that promises a body via ``Content-Length`` then disappears.

    Mirrors the case where gpg-cli's HTTPSConnection has flushed the
    headers but the underlying socket dies before it can write the
    JSON body. The bridge's ``rfile.read(length)`` returns short — we
    rely on Python's ``BaseHTTPRequestHandler`` to surface that as a
    closed-connection error on the handler thread, NOT a server crash.
    """
    config = Config(port=0)
    handle = _start_server(config, gpg_client)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", handle.port))
        sock.sendall(
            b"POST /gpg-bridge/v1/sign HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Authorization: Bearer valid-token\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 9999\r\n\r\n"
            b"{"  # one byte of the promised 9999-byte body, then drop
        )
        # SO_LINGER 0 forces a TCP RST instead of a graceful close — a
        # cleaner approximation of a network drop than ``close()``. The
        # ``struct linger`` shape is two C ints (l_onoff, l_linger) and
        # must be packed with the platform's native int width, hence
        # ``struct.pack("ii", ...)`` rather than a hand-rolled byte
        # literal (which is 4 bytes on Linux's 8-byte struct linger).
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()
        time.sleep(0.1)
        status, body = _post_json(
            f"{handle.base_url}/gpg-bridge/v1/sign",
            {
                "local_user": "test@example.invalid",
                "payload_b64": base64.b64encode(b"after-rst").decode("ascii"),
                "armor": True,
            },
        )
        assert status == 200
        assert body["exit_code"] == 0
    finally:
        handle.close()


@pytest.mark.covers_function("Serve GPG Bridge HTTP API")
def test_repeated_resets_do_not_exhaust_handler_pool(
    gpg_client: GpgSubprocessClient,
) -> None:
    """Many half-open peers must not exhaust the bridge's handler pool.

    ``ThreadingHTTPServer`` spawns one thread per connection. If the
    bridge fails to clean up after a TCP reset, twenty broken peers
    in a row would leave twenty zombie threads (or sockets) hanging
    around. We validate the bridge stays serviceable after a flood.
    """
    config = Config(port=0)
    handle = _start_server(config, gpg_client)
    try:
        for _ in range(20):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", handle.port))
            sock.sendall(b"GARBAGE\r\n\r\n")
            sock.close()
        time.sleep(0.1)
        status, body = _post_json(
            f"{handle.base_url}/gpg-bridge/v1/sign",
            {
                "local_user": "test@example.invalid",
                "payload_b64": base64.b64encode(b"after-flood").decode("ascii"),
                "armor": True,
            },
        )
        assert status == 200
        assert body["exit_code"] == 0
    finally:
        handle.close()
