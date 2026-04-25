# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""In-process HTTP fake for the notification plugin wire protocol.

Replaces the pre-#6 ``NotificationPlugin`` subclasses used across unit
tests. Each test that needs a decision spins up one of these against
``127.0.0.1:0`` (OS-assigned port), passes the URL into
``ApprovalClient``, and tears down in the fixture's finally block.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class NotifierRequest:
    family_id: str
    scope: str
    description: str | None


class NotifierFake:
    """A stoppable, observable HTTP notifier backing unit tests."""

    def __init__(
        self,
        approved: bool = False,
        grant_type: str = "once",
        duration_minutes: int | None = None,
    ):
        # Fail-closed default (``approved=False``) so an accidentally-
        # unset fixture can't silently approve a prompt-tier test.
        self._decision: dict[str, Any] = {
            "approved": approved,
            "grant_type": grant_type,
        }
        if duration_minutes is not None:
            self._decision["duration_minutes"] = duration_minutes
        self.received: list[NotifierRequest] = []

        fake = self  # closure capture

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    parsed = {}
                if isinstance(parsed, dict):
                    fake.received.append(
                        NotifierRequest(
                            family_id=str(parsed.get("family_id", "")),
                            scope=str(parsed.get("scope", "")),
                            description=parsed.get("description"),
                        )
                    )
                body = json.dumps(dict(fake._decision)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        # ``server_address`` is typed as accepting bytes for AF_UNIX;
        # we're always IPv4, so pinning the host type is the cleaner
        # fix than decoding conditionally.
        host, port = self._server.server_address[:2]
        assert isinstance(host, str)
        return f"http://{host}:{port}/"

    def set_decision(
        self,
        approved: bool,
        grant_type: str = "once",
        duration_minutes: int | None = None,
    ) -> None:
        """Swap the fixed response — e.g. to test approve-then-deny."""
        self._decision = {"approved": approved, "grant_type": grant_type}
        if duration_minutes is not None:
            self._decision["duration_minutes"] = duration_minutes

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)
