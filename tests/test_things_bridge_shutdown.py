# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shutdown-handler tests for the things-bridge HTTP server.

Pins the same drain / deadline invariants as ``test_server_shutdown.py``
against the bridge's ``run_server``.
"""

from __future__ import annotations

import json
import signal
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any
from unittest.mock import Mock

import pytest

from tests._signals import invoke_installed_handler
from tests.factories import make_area
from tests.things_client_fake.store import FakeThingsClient, FakeThingsStore
from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config
from things_bridge.server import (
    ThingsBridgeHandler,
    ThingsBridgeServer,
    _install_shutdown_handler,
)


class _AlwaysValidAuthz(AgentAuthClient):
    # Skip AgentAuthClient.__init__: the test never exercises the HTTP path.
    def __init__(self) -> None:
        pass

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        return None


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(0.01)


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_sigterm_triggers_bridge_shutdown(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    drain_complete = _install_shutdown_handler(server, deadline_seconds=5.0)
    try:
        invoke_installed_handler(signal.SIGTERM)
        _wait_until(lambda: server.shutdown.called)
        assert server.shutdown.called
    finally:
        drain_complete.set()


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_sigint_also_triggers_bridge_shutdown(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    drain_complete = _install_shutdown_handler(server, deadline_seconds=5.0)
    try:
        invoke_installed_handler(signal.SIGINT)
        _wait_until(lambda: server.shutdown.called)
        assert server.shutdown.called
    finally:
        drain_complete.set()


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_bridge_shutdown_handler_is_idempotent(preserve_signal_handlers):
    server = Mock(spec=ThreadingHTTPServer)
    drain_complete = _install_shutdown_handler(server, deadline_seconds=5.0)
    try:
        invoke_installed_handler(signal.SIGTERM)
        invoke_installed_handler(signal.SIGTERM)
        invoke_installed_handler(signal.SIGINT)

        _wait_until(lambda: server.shutdown.called, timeout=1.0)
        time.sleep(0.1)
        assert server.shutdown.call_count == 1
    finally:
        drain_complete.set()


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_bridge_watchdog_force_exits_when_drain_exceeds_deadline(
    preserve_signal_handlers, monkeypatch
):
    exit_calls: list[int] = []
    monkeypatch.setattr("things_bridge.server.os._exit", lambda code: exit_calls.append(code))

    server = Mock(spec=ThreadingHTTPServer)
    _install_shutdown_handler(server, deadline_seconds=0.1)
    invoke_installed_handler(signal.SIGTERM)

    _wait_until(lambda: bool(exit_calls))
    assert exit_calls == [1]


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_bridge_watchdog_bounds_server_close_not_just_shutdown(
    preserve_signal_handlers, monkeypatch
):
    """Regression pin: deadline must cover ``server_close`` too.

    See the agent-auth equivalent for rationale — ``server.shutdown()``
    only stops the accept loop; the hung-request protection relies on
    the watchdog still being armed during ``server_close``.
    """
    exit_calls: list[int] = []
    monkeypatch.setattr("things_bridge.server.os._exit", lambda code: exit_calls.append(code))

    server = Mock(spec=ThreadingHTTPServer)
    _install_shutdown_handler(server, deadline_seconds=0.1)
    invoke_installed_handler(signal.SIGTERM)

    _wait_until(lambda: bool(exit_calls))
    assert exit_calls == [1]


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_bridge_server_uses_non_daemon_request_threads():
    assert ThingsBridgeServer.daemon_threads is False


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
def test_in_flight_bridge_request_completes_before_server_close_returns(monkeypatch):
    """Drain must wait for the bridge handler to finish writing its response."""
    store = FakeThingsStore()
    store.areas.append(make_area(id="area-drain-test", name="Drain"))
    things = FakeThingsClient(store)
    authz = _AlwaysValidAuthz()
    config = Config(host="127.0.0.1", port=0)
    server = ThingsBridgeServer(config, things, authz)
    port = server.server_address[1]

    request_entered = threading.Event()
    allow_response = threading.Event()

    original_do_get = ThingsBridgeHandler.do_GET

    def _slow_do_get(self):
        request_entered.set()
        allow_response.wait(timeout=5.0)
        return original_do_get(self)

    monkeypatch.setattr(ThingsBridgeHandler, "do_GET", _slow_do_get)

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    response: list[tuple[int, Any]] = []

    def _client():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/things-bridge/v1/areas",
            headers={"Authorization": "Bearer aa_test_token"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                response.append((resp.status, json.loads(resp.read())))
        except urllib.error.HTTPError as exc:
            response.append((exc.code, json.loads(exc.read())))

    threading.Thread(target=_client, daemon=True).start()
    assert request_entered.wait(timeout=2.0), "bridge request never reached the handler"

    threading.Thread(target=server.shutdown, daemon=True).start()
    allow_response.set()

    serve_thread.join(timeout=3.0)
    assert not serve_thread.is_alive()

    close_thread = threading.Thread(target=server.server_close, daemon=True)
    close_thread.start()
    close_thread.join(timeout=3.0)
    assert not close_thread.is_alive()

    assert len(response) == 1, "in-flight bridge request was dropped"
    status, body = response[0]
    assert status == 200, body
    assert body["areas"][0]["id"] == "area-drain-test"
