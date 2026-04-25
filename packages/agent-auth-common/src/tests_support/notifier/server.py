# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tiny fixed-decision HTTP notifier for integration-test containers."""

from __future__ import annotations

import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import BaseServer
from typing import Any


def _make_handler(decision: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    """Build a handler class that returns ``decision`` on every POST."""

    class _FixedHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                # Drain the request body before replying; leaving data in
                # the socket buffer confuses urllib's keep-alive logic.
                self.rfile.read(length)
            body = json.dumps(decision).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _FixedHandler


def install_shutdown_handler(server: BaseServer) -> None:
    """Install SIGTERM / SIGINT handlers that kick ``serve_forever`` out.

    Only safe to call from the main thread of the main interpreter
    (``signal.signal`` raises ``ValueError`` elsewhere). The
    ``python -m tests_support.notifier`` entrypoint enables it via
    ``run_fixed_notifier(..., install_signal_handlers=True)``; in-process
    callers (the unit tests) leave it off so signal-handler installation
    never grabs pytest's main thread.

    The handler is required because ``python -m tests_support.notifier``
    runs as PID 1 inside the integration-test compose container. The
    Linux kernel treats PID 1 specially: signals with no installed
    handler are silently *ignored* — not default-action, despite the
    C-level ``SIG_DFL`` semantics for non-PID-1 processes. Without
    this handler, ``docker compose stop`` waits the full
    ``stop_grace_period`` and SIGKILLs the container at the boundary,
    which produced the consistent ~6 s teardown ceiling diagnosed in
    #294 (every notifier instance exited 137).

    Calling ``server.shutdown()`` from the signal-handler frame would
    deadlock against ``serve_forever`` (the same caveat that drives
    ``packages/agent-auth/src/agent_auth/server.py``'s handler), so we
    dispatch it onto a daemon thread and let the main thread keep
    spinning until ``serve_forever`` returns.
    """

    def _handle(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def run_fixed_notifier(
    host: str,
    port: int,
    approved: bool,
    *,
    install_signal_handlers: bool = False,
) -> None:
    """Serve a notifier that returns the same decision on every POST.

    Blocks until interrupted. The decision body is deliberately the
    minimum the wire protocol requires so tests don't accidentally
    couple to optional fields the server may add later.

    Pass ``install_signal_handlers=True`` only when running this on the
    main thread of the main interpreter (e.g. the
    ``python -m tests_support.notifier`` script entrypoint). The
    in-process unit tests start the notifier from a daemon thread and
    pass the default (``False``) — installing signal handlers there
    would raise ``ValueError`` from ``signal.signal``.
    """
    decision = {"approved": approved, "grant_type": "once"}
    handler = _make_handler(decision)
    server = ThreadingHTTPServer((host, port), handler)
    bound = server.server_address[1]
    mode = "approve" if approved else "deny"
    print(
        f"tests_support.notifier {mode} listening on http://{host}:{bound}",
        flush=True,
    )
    if install_signal_handlers:
        install_shutdown_handler(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
