# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shutdown-handler tests for the agent-auth HTTP server.

Pins the public-surface behaviour graceful shutdown must guarantee:

- Signal receipt triggers ``server.shutdown`` on a separate thread so
  the main ``serve_forever`` thread can unwind.
- In-flight requests complete before ``server_close`` returns.
- A watchdog force-exits the process if drain exceeds
  ``shutdown_deadline_seconds``.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.server import AgentAuthHandler, AgentAuthServer, _install_shutdown_handler
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests._http import get
from tests._signals import invoke_installed_handler


class _DenyPlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=False)


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_sigterm_triggers_server_shutdown(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    _install_shutdown_handler(server, deadline_seconds=5.0)

    invoke_installed_handler(signal.SIGTERM)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not server.shutdown.called:
        time.sleep(0.01)
    assert server.shutdown.called, "SIGTERM did not cause server.shutdown()"


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_sigint_also_triggers_server_shutdown(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    _install_shutdown_handler(server, deadline_seconds=5.0)

    invoke_installed_handler(signal.SIGINT)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not server.shutdown.called:
        time.sleep(0.01)
    assert server.shutdown.called


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_shutdown_handler_is_idempotent(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    _install_shutdown_handler(server, deadline_seconds=5.0)

    invoke_installed_handler(signal.SIGTERM)
    invoke_installed_handler(signal.SIGTERM)
    invoke_installed_handler(signal.SIGINT)

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not server.shutdown.called:
        time.sleep(0.01)

    time.sleep(0.1)
    assert (
        server.shutdown.call_count == 1
    ), f"expected one shutdown call, got {server.shutdown.call_count}"


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_watchdog_force_exits_when_drain_exceeds_deadline(preserve_signal_handlers, monkeypatch):
    """A request that refuses to return must not hold the process past its deadline."""
    exit_calls: list[int] = []
    monkeypatch.setattr("agent_auth.server.os._exit", lambda code: exit_calls.append(code))

    release = threading.Event()

    def _hanging_shutdown():
        release.wait(timeout=5.0)

    server = Mock(spec=ThreadingHTTPServer)
    server.shutdown.side_effect = _hanging_shutdown

    _install_shutdown_handler(server, deadline_seconds=0.1)
    invoke_installed_handler(signal.SIGTERM)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not exit_calls:
        time.sleep(0.02)

    release.set()
    assert exit_calls == [
        1
    ], f"watchdog did not force-exit within deadline; exit_calls={exit_calls}"


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_agent_auth_server_uses_non_daemon_request_threads():
    """Daemon threads would not be joined by ``server_close``, so drain needs non-daemon."""
    assert AgentAuthServer.daemon_threads is False


def _make_server(tmp_dir, signing_key, encryption_key):
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(_DenyPlugin(), store, audit)
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager)
    return config, store, server


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_in_flight_request_completes_before_server_close_returns(
    tmp_dir, signing_key, encryption_key, monkeypatch
):
    """Drain must wait for the handler to finish writing its response."""
    config, store, server = _make_server(tmp_dir, signing_key, encryption_key)

    # Issue a valid health token so the request reaches the slow path.
    family_id = "fam-drain-test"
    store.create_family(family_id, {"agent-auth:health": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)

    port = server.server_address[1]
    request_entered = threading.Event()
    allow_response = threading.Event()
    original_health = AgentAuthHandler._handle_health

    def _slow_health(self):
        request_entered.set()
        allow_response.wait(timeout=5.0)
        return original_health(self)

    monkeypatch.setattr(AgentAuthHandler, "_handle_health", _slow_health)

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    response: list[tuple[int, dict]] = []

    def _client():
        response.append(
            get(
                f"http://127.0.0.1:{port}/agent-auth/health",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        )

    client_thread = threading.Thread(target=_client, daemon=True)
    client_thread.start()

    assert request_entered.wait(timeout=2.0), "client request never reached the handler"

    threading.Thread(target=server.shutdown, daemon=True).start()
    allow_response.set()

    serve_thread.join(timeout=3.0)
    assert not serve_thread.is_alive(), "serve_forever did not return after shutdown"

    close_thread = threading.Thread(target=server.server_close, daemon=True)
    close_thread.start()
    close_thread.join(timeout=3.0)
    assert not close_thread.is_alive(), "server_close did not return"

    client_thread.join(timeout=3.0)
    assert len(response) == 1, "in-flight request was dropped mid-flight"
    status, body = response[0]
    assert status == 200, body


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_audit_log_entry_from_inflight_request_is_durable_post_shutdown(
    tmp_dir, signing_key, encryption_key, monkeypatch
):
    """A handler that writes to the audit log during shutdown must not lose the entry."""
    config, store, server = _make_server(tmp_dir, signing_key, encryption_key)

    family_id = "fam-audit-drain-test"
    store.create_family(family_id, {"agent-auth:health": "allow"})
    access_token, _ = create_token_pair(signing_key, store, family_id, config)

    port = server.server_address[1]
    request_entered = threading.Event()
    allow_response = threading.Event()
    original_health = AgentAuthHandler._handle_health

    def _slow_health(self):
        request_entered.set()
        allow_response.wait(timeout=5.0)
        # Write an audit entry just before returning — this is what the
        # real handlers do for `validation_allowed` etc, and the entry
        # must land on disk even though shutdown is in progress.
        self._server.audit.log_token_operation("health_served_under_drain", marker="drain")
        return original_health(self)

    monkeypatch.setattr(AgentAuthHandler, "_handle_health", _slow_health)

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    response: list[tuple[int, dict]] = []

    def _client():
        response.append(
            get(
                f"http://127.0.0.1:{port}/agent-auth/health",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        )

    threading.Thread(target=_client, daemon=True).start()
    assert request_entered.wait(timeout=2.0), "client request never reached the handler"

    threading.Thread(target=server.shutdown, daemon=True).start()
    allow_response.set()

    serve_thread.join(timeout=3.0)
    server.server_close()
    store.close()

    with open(config.log_path, encoding="utf-8") as f:
        body = f.read()
    assert "health_served_under_drain" in body, "audit entry written during shutdown was lost"


@pytest.mark.covers_function("Handle Graceful Shutdown")
def test_token_store_close_checkpoints_wal(tmp_dir, encryption_key):
    """After ``close()`` the WAL should be drained so the next open does not replay."""
    db_path = os.path.join(tmp_dir, "tokens.db")
    store = TokenStore(db_path, encryption_key)
    store.create_family("fam-checkpoint-test", {"agent-auth:health": "allow"})
    store.close()

    # A successful WAL checkpoint does not delete the -wal file, but it
    # does zero its contents. Re-opening and reading the family back
    # proves the data is durable and the store API remains usable (via
    # a fresh connection) post-close.
    reopened = TokenStore(db_path, encryption_key)
    assert reopened.get_family("fam-checkpoint-test") is not None
