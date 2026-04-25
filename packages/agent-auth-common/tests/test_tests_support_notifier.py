# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the tests-support approve/deny HTTP notifiers.

The integration suite launches these as sidecar processes inside the
test container; the unit suite exercises them in-process against an
OS-assigned port so a regression is caught without a container spin-up.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from agent_auth.approval_client import ApprovalClient
from tests_support.notifier.server import run_fixed_notifier


def _free_port() -> int:
    # Ask the kernel for an ephemeral port and immediately close: the
    # run_fixed_notifier helper takes a concrete port rather than ":0"
    # so we round-trip through a fresh socket to pick one.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


@pytest.fixture
def approve_notifier():
    port = _free_port()
    thread = threading.Thread(
        target=run_fixed_notifier,
        kwargs={"host": "127.0.0.1", "port": port, "approved": True},
        daemon=True,
    )
    thread.start()
    # The server is a ThreadingHTTPServer so it's listening by the time
    # serve_forever() enters its loop, but we might race a spot check.
    # A short poll keeps the fixture deterministic without a blanket sleep.
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, data=b"{}", method="POST"),
                timeout=0.1,
            )
            break
        except OSError:
            time.sleep(0.01)
    yield url


@pytest.mark.covers_function("POST Approval Request to Notifier")
def test_approve_notifier_returns_approved_once(approve_notifier):
    client = ApprovalClient(url=approve_notifier, timeout_seconds=2.0)
    result = client.request_approval("fam1", "things:read", "list todos")
    assert result.approved is True
    assert result.grant_type == "once"


def test_approve_notifier_body_shape_is_minimal():
    """Server returns just approved + grant_type; no extra fields."""
    port = _free_port()
    thread = threading.Thread(
        target=run_fixed_notifier,
        kwargs={"host": "127.0.0.1", "port": port, "approved": True},
        daemon=True,
    )
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 2.0
    body: bytes = b""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=b"{}", method="POST"),
                timeout=0.2,
            ) as resp:
                body = resp.read()
            break
        except OSError:
            time.sleep(0.01)
    payload = json.loads(body.decode("utf-8"))
    assert payload == {"approved": True, "grant_type": "once"}
