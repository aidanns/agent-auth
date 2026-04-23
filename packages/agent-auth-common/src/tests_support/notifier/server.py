# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tiny fixed-decision HTTP notifier for integration-test containers."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def run_fixed_notifier(host: str, port: int, approved: bool) -> None:
    """Serve a notifier that returns the same decision on every POST.

    Blocks until interrupted. The decision body is deliberately the
    minimum the wire protocol requires so tests don't accidentally
    couple to optional fields the server may add later.
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
