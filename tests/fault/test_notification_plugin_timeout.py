# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: out-of-process notifier timeout / unavailable.

After #6 the notifier is a separate HTTP process. Its failure modes
are now connection errors (notifier not running), read timeouts
(notifier hangs), non-2xx responses (notifier crashes mid-request),
and malformed JSON (notifier returns garbage). ``ApprovalClient``
must fail closed on all of them — silently approving on any notifier
failure would defeat the whole trust-boundary goal #6 exists for.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient
from agent_auth.audit import AuditLogger
from agent_auth.keys import EncryptionKey
from agent_auth.store import TokenStore
from tests.fault.conftest import read_audit_events


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    return TokenStore(str(tmp_path / "tokens.db"), EncryptionKey(os.urandom(32)))


def _pick_closed_port() -> int:
    """Return an ephemeral port the kernel handed us and then closed."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_notifier_unreachable_denies_without_raising(store: TokenStore, audit: AuditLogger) -> None:
    """Connecting to a closed port fails closed — no exception to caller."""
    client = ApprovalClient(url=f"http://127.0.0.1:{_pick_closed_port()}/", timeout_seconds=1.0)
    manager = ApprovalManager(client, store=store, audit=audit)
    result = manager.request_approval("fam-1", "things:read", description="list todos")
    assert result.approved is False


def _start_hanging_notifier() -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    """Serve one notifier that sleeps past the client timeout."""

    class _Hang(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            # Sleep longer than the test's client timeout; the client
            # must give up and return deny rather than hang the caller.
            time.sleep(5.0)
            body = json.dumps({"approved": True, "grant_type": "once"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hang)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}/", server, thread


def test_notifier_timeout_denies_without_raising(store: TokenStore, audit: AuditLogger) -> None:
    url, server, thread = _start_hanging_notifier()
    try:
        client = ApprovalClient(url=url, timeout_seconds=0.2)
        manager = ApprovalManager(client, store=store, audit=audit)
        result = manager.request_approval("fam-1", "things:read", description="list todos")
        assert result.approved is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _start_error_notifier(status: int) -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    class _Err(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Err)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    return f"http://{host}:{port}/", server, thread


def test_notifier_500_denies_without_raising(store: TokenStore, audit: AuditLogger) -> None:
    """An internal-server-error from the notifier must fail closed."""
    url, server, thread = _start_error_notifier(500)
    try:
        client = ApprovalClient(url=url, timeout_seconds=2.0)
        manager = ApprovalManager(client, store=store, audit=audit)
        result = manager.request_approval("fam-1", "things:read", description="list todos")
        assert result.approved is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_notifier_failure_does_not_leave_stale_grant(
    store: TokenStore, audit: AuditLogger, audit_log_path: Path
) -> None:
    """A failed notifier call must not record an ``approval_granted`` event.

    The audit stream is the authoritative record of what actually
    happened; emitting ``approval_granted`` on a notifier failure
    would give an operator a false "user approved this request"
    signal. The denied outcome is still audited as ``approval_denied``
    so there's no silent gap.
    """
    client = ApprovalClient(url=f"http://127.0.0.1:{_pick_closed_port()}/", timeout_seconds=1.0)
    manager = ApprovalManager(client, store=store, audit=audit)
    manager.request_approval("fam-1", "things:read")

    events = read_audit_events(audit_log_path)
    assert not any(e.get("event") == "approval_granted" for e in events)
    assert not manager.check_timed_grant("fam-1", "things:read")
